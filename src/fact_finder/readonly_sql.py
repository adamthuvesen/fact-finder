"""Decide whether a preserved SQL file is read-only by parsing it with sqlglot.

The dialect of a preserved query is unknown, and dialects disagree about where a
string ends. `'a\\'; DROP TABLE t; --'` is one literal in BigQuery and a write in
Postgres. So the text is parsed under every reading in `DIALECTS`. It is accepted
only if at least one reading parses and every reading that parses is read-only.
If no reading parses, or a reading crashes the parser, it is rejected.

Comments get two checks on the raw text, because a comment is invisible to the parser.
MySQL runs `/*! ... */` as SQL, and engines disagree on whether block comments nest. A
string literal holding those characters is rejected too. That false positive is
accepted, because the alternative is a missed write.

sqlglot also reads some writes as reads, so tokens get checked too. Snowflake's `->>` flow
operator runs a second statement, and T-SQL needs no semicolon between statements. sqlglot
reads the `DELETE` in `SELECT 1 ->> DELETE FROM t` and `SELECT 1 DELETE FROM t` as a column
or an alias. So `->>` must be followed by a literal, its JSON use. A bare statement keyword
is rejected in any position. A column with such a name needs quotes or a table qualifier.

This parser is defence in depth. It rejects built-in functions with a known side effect,
such as `setval` and `pg_terminate_backend`. It cannot detect `SELECT side_effect_proc()`:
a user function call looks the same whether or not the function writes. The read-only
role on the connection is the real guard.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import reduce
from typing import Self

import sqlglot
from sqlglot import Token, TokenType, exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ParseError, TokenError

DIALECTS = (
    "postgres",
    "duckdb",
    "snowflake",
    "bigquery",
    "mysql",
    "redshift",
    "databricks",
    "tsql",
)

WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Copy,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.NextValueFor,
)
# Built-in functions that write, kill a session, or touch the server's files from a SELECT.
SIDE_EFFECT_FUNCTIONS = frozenset(
    {
        "SETVAL",
        "PG_TERMINATE_BACKEND",
        "PG_CANCEL_BACKEND",
        "PG_RELOAD_CONF",
        "PG_ROTATE_LOGFILE",
        "DBLINK_EXEC",
        "LO_IMPORT",
        "LO_EXPORT",
        "LO_UNLINK",
        "LO_CREATE",
    }
)
# T-SQL table hints that take write locks, like FOR UPDATE.
LOCK_HINTS = frozenset({"UPDLOCK", "XLOCK", "TABLOCKX", "HOLDLOCK"})
USE_KINDS = frozenset({"WAREHOUSE", "DATABASE", "SCHEMA"})
METADATA_PRAGMAS = frozenset(
    {
        "database_list",
        "show_databases",
        "show_tables",
        "show_tables_expanded",
        "table_info",
        "version",
    }
)
EXPLAIN_OPTIONS = re.compile(
    r"^\s*(?:\([^)]*\)|(?:ANALYZE|VERBOSE|FORMATTED|EXTENDED|FORMAT\s*=\s*\w+|USING\s+\w+|QUERY\s+PLAN(?:\s+FOR)?)\b)",
    re.IGNORECASE,
)
NO_SQL_REASON = re.compile(r"^\s*--\s*no sql used:\s*(\S.*)$", re.IGNORECASE | re.M)
QUERY_ID = re.compile(r"^\s*query_id:\s*(\S+)\s*$", re.IGNORECASE)
EXECUTABLE_COMMENT = re.compile(r"/\*M?!", re.IGNORECASE)
NESTED_COMMENT = re.compile(r"/\*(?:(?!\*/).)*?/\*", re.DOTALL)
LOCKING_CLAUSE = re.compile(
    r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|UPDATE|SHARE)\b"
    r"(?:\s+OF\s+[\w.\"]+(?:\s*,\s*[\w.\"]+)*)?"
    r"(?:\s+NOWAIT\b|\s+SKIP\s+LOCKED\b)?"
    r"|\bLOCK\s+IN\s+SHARE\s+MODE\b",
    re.IGNORECASE,
)
STATEMENT_KEYWORDS = frozenset(
    {
        "ALTER",
        "CALL",
        "CREATE",
        "DELETE",
        "DROP",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "INSERT",
        "MERGE",
        "REVOKE",
        "TRUNCATE",
        "UPDATE",
    }
)
CHAINING_OPERATORS = (TokenType.ARROW, TokenType.PIPE_GT)
BARE_EXPRESSIONS = (exp.Alias, exp.Anonymous, exp.Column)
# A delimiter some dialects lack reads as plain text there, so those readings accept an
# unterminated form. Tokenize it under a dialect that has the delimiter.
UNTERMINATED_CHECKS = (
    (re.compile(r"(?<![\w$])\$\w*\$"), "postgres", "dollar-quoted string"),
    (re.compile(r"`"), "mysql", "backtick identifier"),
)
# sqlglot raises these on some malformed input instead of ParseError.
PARSER_CRASHES = (IndexError, KeyError, AttributeError, TypeError, RecursionError)

# sqlglot logs a warning each time a reading falls back to `Command`, and this
# module parses every text eight times.
logging.getLogger("sqlglot").setLevel(logging.ERROR)


class UnsafeSqlError(ValueError):
    """Raised when SQL does not parse or is not read-only under some reading."""


def _is_quoted(token: Token) -> bool:
    name = token.token_type.name
    return name in {"IDENTIFIER", "STRING"} or name.endswith("_STRING")


def _is_literal(token: Token) -> bool:
    return token.token_type == TokenType.NUMBER or (
        _is_quoted(token) and token.token_type != TokenType.IDENTIFIER
    )


def _is_statement_keyword(token: Token) -> bool:
    return not _is_quoted(token) and token.text.upper() in STATEMENT_KEYWORDS


def _is_bare_keyword(tokens: list[Token], index: int) -> bool:
    """Tell a statement keyword from a function such as `INSERT(` or a name after `t.`."""
    previous = tokens[index - 1] if index else None
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    return (
        _is_statement_keyword(tokens[index])
        and (previous is None or previous.token_type != TokenType.DOT)
        and (following is None or following.token_type != TokenType.L_PAREN)
    )


def _token_problem(sql: str, dialect: str, *, in_show: bool = False) -> str | None:
    """Find what the parser reads as harmless: flow operators and bare keywords."""
    tokens = Dialect.get_or_raise(dialect).tokenize(sql)
    at_start = not in_show
    for index, token in enumerate(tokens):
        if token.token_type == TokenType.SEMICOLON:
            at_start, in_show = True, False
            continue
        if at_start:
            # `SHOW CREATE TABLE t` is a read.
            in_show = token.text.upper() == "SHOW"
            at_start = False
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token.token_type == TokenType.DARROW and not (following and _is_literal(following)):
            return "uses ->> without a literal, which Snowflake runs as a second statement"
        if (
            token.token_type in CHAINING_OPERATORS
            and following
            and _is_statement_keyword(following)
        ):
            return f"chains {following.text.upper()} with {token.text}"
        if not in_show and _is_bare_keyword(tokens, index):
            return f"has a bare {token.text.upper()}; quote it if it is a column"
    return None


def _write_in_tree(statement: exp.Expr) -> str | None:
    node = statement.find(*WRITE_NODES)
    if node is not None:
        return f"contains a {type(node).__name__.upper()}"
    for function in statement.find_all(exp.Anonymous):
        if function.name.upper().startswith("SYSTEM$"):
            return f"calls {function.name}"
        if function.name.upper() == "NEXTVAL":
            return "advances a sequence with NEXTVAL"
        if function.name.upper() in SIDE_EFFECT_FUNCTIONS:
            return f"calls {function.name}, which has a side effect"
    for column in statement.find_all(exp.Column):
        if column.table and column.name.upper() == "NEXTVAL":
            return "advances a sequence with NEXTVAL"
    return _lock_hint(statement)


def _lock_hint(statement: exp.Expr) -> str | None:
    for hint in statement.find_all(exp.WithTableHint):
        locks = {word.upper() for word in re.findall(r"\w+", hint.sql())} & LOCK_HINTS
        if locks:
            return f"takes a write lock with {min(locks)}"
    return None


def _explain_problem(body: str, dialect: str) -> str | None:
    remainder = body
    while (match := EXPLAIN_OPTIONS.match(remainder)) is not None:
        remainder = remainder[match.end() :]
    try:
        statements = sqlglot.parse(remainder, dialect=dialect)
    except ParseError, TokenError:
        return "EXPLAIN has a body that does not parse"
    for statement in statements:
        if statement is not None and (problem := _statement_problem(statement, dialect)):
            return f"EXPLAIN body {problem}"
    return None


def _command_problem(command: exp.Command, dialect: str) -> str | None:
    verb = command.name.upper()
    if verb == "SHOW":
        try:
            return _token_problem(command.text("expression"), dialect, in_show=True)
        except TokenError:
            return "SHOW has a body that does not tokenize"
    if verb == "EXPLAIN":
        return _explain_problem(command.text("expression"), dialect)
    return f"runs {verb}"


def _use_problem(use: exp.Use) -> str | None:
    kind = use.args.get("kind")
    if kind is None:
        return None
    name = kind.name if isinstance(kind, exp.Expr) else str(kind)
    return None if name.upper() in USE_KINDS else f"switches {name.upper()}"


def _pragma_problem(pragma: exp.Pragma) -> str | None:
    target = pragma.this
    if not isinstance(target, exp.Anonymous | exp.Column):
        return "sets a PRAGMA"
    name = target.name.lower()
    return None if name in METADATA_PRAGMAS else f"runs PRAGMA {name}"


def _statement_problem(statement: exp.Expr, dialect: str) -> str | None:
    match statement:
        case exp.Command():
            return _command_problem(statement, dialect)
        case exp.Use():
            return _use_problem(statement)
        case exp.Pragma():
            return _pragma_problem(statement)
        case exp.Query() | exp.Describe() | exp.Show() | exp.Values() | exp.Summarize():
            return _write_in_tree(statement)
        case _:
            return f"is a {type(statement).__name__.upper()} statement"


def _reading_problem(statements: list[exp.Expr | None], dialect: str) -> str | None:
    for statement in statements:
        if statement is None or isinstance(statement, (exp.Semicolon, *BARE_EXPRESSIONS)):
            continue
        if (problem := _statement_problem(statement, dialect)) is not None:
            return f"{statement.sql(dialect=dialect)[:80]!r} {problem}"
    return None


def _statement_count(statements: list[exp.Expr | None]) -> int:
    return sum(
        statement is not None and not isinstance(statement, exp.Semicolon)
        for statement in statements
    )


def _recognized(statements: list[exp.Expr | None]) -> bool:
    """Tell whether this reading understood every statement.

    A dialect that lacks a verb reads `SUMMARIZE t` as a column alias and `VALUES (1)`
    as a function call. Such a reading has no opinion on that statement.
    """
    return not any(isinstance(statement, BARE_EXPRESSIONS) for statement in statements)


def _bound_query_ids(sql: str, dialect: str) -> set[str]:
    """Return ids in a comment that leads a statement, so each id has a query."""
    ids: set[str] = set()
    at_statement_start = True
    for token in Dialect.get_or_raise(dialect).tokenize(sql):
        if token.token_type == TokenType.SEMICOLON:
            at_statement_start = True
            continue
        if at_statement_start:
            ids.update(
                match.group(1) for comment in token.comments if (match := QUERY_ID.match(comment))
            )
        at_statement_start = False
    return ids


def _reject_unterminated(text: str) -> None:
    for pattern, dialect, label in UNTERMINATED_CHECKS:
        if pattern.search(text):
            try:
                Dialect.get_or_raise(dialect).tokenize(text)
            except TokenError as exc:
                raise UnsafeSqlError(f"contains an unterminated {label}") from exc


def locking_clause_is_the_problem(sql: str) -> bool:
    """Say whether the text is read-only once its locking clauses go. This chooses a Fix.

    `ReadOnlySql.parse` alone decides safety.
    """
    without_locks = LOCKING_CLAUSE.sub("", sql)
    if without_locks == sql:
        return False
    try:
        ReadOnlySql.parse(without_locks)
    except UnsafeSqlError:
        return False
    return True


def first_unsafe_line(sql: str) -> int | None:
    """Point a message at the first `;`-separated part that fails alone.

    This only helps a person find the problem. `ReadOnlySql.parse` alone decides safety.
    """
    line = 1
    for part in sql.split(";"):
        try:
            ReadOnlySql.parse(part)
        except UnsafeSqlError:
            offset = next(
                (
                    index
                    for index, text in enumerate(part.splitlines())
                    if text.strip() and not text.lstrip().startswith("--")
                ),
                0,
            )
            return line + offset
        line += part.count("\n")
    return None


@dataclass(frozen=True)
class ReadOnlySql:
    """SQL text that every parsing reading agrees is read-only."""

    text: str
    statement_count: int
    query_ids: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, sql: str) -> Self:
        """Return the checked text, or raise `UnsafeSqlError`.

        Text holding only comments is valid with `statement_count` zero, so a
        scaffolded `queries.sql` passes the structural check.
        """
        text = sql.removeprefix("\ufeff")
        if EXECUTABLE_COMMENT.search(text):
            raise UnsafeSqlError("contains an executable /*! comment, which MySQL runs")
        if NESTED_COMMENT.search(text):
            raise UnsafeSqlError("contains a nested block comment, which engines read differently")
        _reject_unterminated(text)
        counts: list[int] = []
        query_ids: list[set[str]] = []
        for dialect in DIALECTS:
            try:
                statements = sqlglot.parse(text, dialect=dialect)
                problem = _reading_problem(statements, dialect) or _token_problem(text, dialect)
                if problem is not None:
                    raise UnsafeSqlError(f"{dialect} reading: {problem}")
                if _recognized(statements):
                    counts.append(_statement_count(statements))
                    query_ids.append(_bound_query_ids(text, dialect))
            except ParseError, TokenError:
                continue
            except PARSER_CRASHES as exc:
                raise UnsafeSqlError(
                    f"{dialect} reading: the parser failed with {type(exc).__name__}"
                ) from exc
        if not counts:
            raise UnsafeSqlError("no SQL dialect could parse this text")
        return cls(
            text=text,
            statement_count=max(counts),
            query_ids=frozenset(reduce(set[str].intersection, query_ids)),
        )

    @property
    def no_sql_reason(self) -> str | None:
        """The reason in a `-- No SQL used: <reason>` line of a statement-free file."""
        if self.statement_count:
            return None
        match = NO_SQL_REASON.search(self.text)
        return match.group(1).strip() if match else None
