"""Read-only SQL parsing shared by validation and warehouse bundles.

Preserved evidence queries must be re-runnable without side effects. The checks
here are deliberately conservative: they strip comments and quoted literals so
keywords inside strings never trip the scan, then require every statement to
start with a read verb and contain no write verb anywhere.

``USE`` is allowed because the shipped Snowflake allowlist
(``config/snowflake-mcp-tools.yaml``) permits it — session context selection is
not a write, and rejecting it here would fail SQL the MCP server legitimately
ran. ``PRAGMA`` is allowed for DuckDB metadata discovery.
"""

from __future__ import annotations

import re

ALLOWED_SQL_STARTS = frozenset(
    {"DESC", "DESCRIBE", "EXPLAIN", "PRAGMA", "SELECT", "SHOW", "USE", "WITH"}
)

# COPY stays forbidden even though `COPY ... TO STDOUT` reads in Postgres:
# `COPY ... FROM` writes, and the two are not worth distinguishing here.
FORBIDDEN_SQL_WORDS = frozenset(
    {
        "ALTER",
        "CALL",
        "COPY",
        "CREATE",
        "DELETE",
        "DROP",
        "EXECUTE",
        "GET",
        "GRANT",
        "INSERT",
        # `SELECT ... INTO` creates a table in Postgres and SQL Server, and
        # `INTO OUTFILE` writes a file in MySQL. `INSERT INTO` is already caught
        # by INSERT, so this costs a genuine read nothing.
        "INTO",
        "MERGE",
        "PUT",
        "REMOVE",
        "REVOKE",
        "TRUNCATE",
        "UPDATE",
        "UPSERT",
    }
)


def sql_code_only(sql: str) -> str:
    """Blank out comments and quoted contents while preserving SQL structure.

    Replacements are length-preserving so statement splitting still lines up
    with the original text.
    """
    result: list[str] = []
    index = 0
    state = "code"
    quote = ""
    quote_start = 0

    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""

        if state == "code":
            if char == "-" and following == "-":
                result.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and following == "*":
                result.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char in {"'", '"'}:
                quote_start = index
                result.append(" ")
                quote = char
                state = "quote"
                index += 1
                continue
            if (
                char == "$"
                and following == "$"
                and (index == 0 or not re.match(r"[A-Za-z0-9_$]", sql[index - 1]))
            ):
                result.extend("  ")
                state = "dollar_quote"
                index += 2
                continue
            result.append(char)
            index += 1
            continue

        if state == "line_comment":
            result.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
            index += 1
            continue

        if state == "block_comment":
            if char == "*" and following == "/":
                result.extend("  ")
                index += 2
                state = "code"
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if state == "dollar_quote":
            if char == "$" and following == "$":
                result.extend("  ")
                index += 2
                state = "code"
            else:
                result.append("\n" if char == "\n" else " ")
                index += 1
            continue

        if quote == "'" and char == "\\" and following:
            result.extend("  ")
            index += 2
            continue

        if char == quote and following == quote:
            result.extend("  ")
            index += 2
        elif char == quote:
            if quote == '"' and re.fullmatch(
                r"(?:SYSTEM\$[A-Z_0-9]+|NEXTVAL)",
                sql[quote_start + 1 : index].upper(),
            ):
                raise ValueError("system functions and sequence operations are blocked")
            result.append(" ")
            index += 1
            state = "code"
        else:
            result.append("\n" if char == "\n" else " ")
            index += 1

    if state in {"block_comment", "quote", "dollar_quote"}:
        raise ValueError("SQL contains an unterminated comment or quoted value")
    return "".join(result)


def sql_statements(code_only_sql: str) -> list[str]:
    """Split sanitized SQL into non-empty statements."""
    return [
        statement.strip() for statement in code_only_sql.split(";") if statement.strip()
    ]


def sql_words(statement: str) -> list[str]:
    return re.findall(r"[A-Za-z_]+", statement.upper())


def first_forbidden_sql_word(code_only_sql: str) -> str | None:
    side_effect = re.search(
        r"\b(?:SYSTEM\$[A-Z_0-9]+|NEXTVAL)\b", code_only_sql.upper()
    )
    if side_effect:
        return side_effect.group()
    for word in sql_words(code_only_sql):
        if word in FORBIDDEN_SQL_WORDS:
            return word
    return None


def statement_start(statement: str) -> str | None:
    words = sql_words(statement)
    return words[0] if words else None
