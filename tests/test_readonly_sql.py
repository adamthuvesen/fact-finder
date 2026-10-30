from __future__ import annotations

import pytest

from agentic_research_loop.readonly_sql import ReadOnlySql, UnsafeSqlError


@pytest.mark.parametrize(
    "sql",
    [
        r"SELECT 'it\'s'; DROP TABLE t; -- '",
        r"SELECT 'a\'; DROP TABLE t; --'",
        "SELECT $a$ $$ $a$; DROP TABLE t; -- $$",
        "SELECT $$text$$; DELETE FROM t",
        "USE ROLE ACCOUNTADMIN",
        "USE SECONDARY ROLES ALL",
        "PRAGMA writable_schema=1",
        "SELECT a FROM t FOR UPDATE",
        "CALL do_thing()",
        "SELEC a FRM",
        "SELECT SYSTEM$CANCEL_ALL_QUERIES()",
        'SELECT "SYSTEM$CANCEL_ALL_QUERIES"()',
        "SELECT seq.NEXTVAL",
        "SELECT nextval('s')",
        "SELECT NEXT VALUE FOR s",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "EXPLAIN ANALYZE DELETE FROM t",
        "EXPLAIN (ANALYZE) DELETE FROM t",
        "SELECT a INTO b FROM c",
        "SELECT 'never closed",
        "INSERT INTO t VALUES (1)",
        "/*! DROP TABLE t */",
        "SELECT 1 /*!50000 INTO OUTFILE '/tmp/x' */",
        "/* /* */ DROP TABLE t; /* */ */ SELECT 1",
        "/*M! DROP TABLE t */",
        "SHOW TABLE --",
        "(" * 5000 + "SELECT 1" + ")" * 5000,
        "FOO bar",
        "side_effect_proc()",
        "SUMMARIZE t; DROP TABLE t",
        "VALUES (1); DROP TABLE t",
    ],
)
def test_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        ReadOnlySql.parse(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT GET(payload,'a') FROM t",
        "SELECT 1 AS use",
        'SELECT 1 AS "NEXTVAL"',
        "SELECT nextval FROM t",
        r"SELECT 'dir\' AS p",
        "USE WAREHOUSE ANALYTICS",
        "SHOW TABLES",
        "DESCRIBE TABLE t",
        "SELECT f.value FROM t, LATERAL FLATTEN(input => t.v) f",
        "SELECT 'DROP TABLE t' AS note",
        "PRAGMA table_info('t')",
        "EXPLAIN SELECT 1",
        "SELECT 1 UNION SELECT 2",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT 1;\n-- a trailing comment holds a Semicolon node",
        "VALUES (1)",
        "EXPLAIN FORMAT=JSON SELECT 1",
        "SUMMARIZE t",
        "\ufeffSELECT 1",
    ],
)
def test_accepted(sql: str) -> None:
    assert ReadOnlySql.parse(sql).statement_count >= 1


def test_undetectable_side_effect_function_is_accepted() -> None:
    """This pins the documented limit: the read-only role is the real guard."""
    assert ReadOnlySql.parse("SELECT side_effect_proc()").statement_count == 1


def test_comment_only_text_has_no_statements() -> None:
    parsed = ReadOnlySql.parse("-- nothing preserved here\n")

    assert parsed.statement_count == 0
    assert parsed.no_sql_reason is None


def test_no_sql_reason_is_read_from_a_statement_free_file() -> None:
    parsed = ReadOnlySql.parse(
        "-- No SQL used: the case reads a CSV.\n-- More detail.\n"
    )

    assert parsed.statement_count == 0
    assert parsed.no_sql_reason == "the case reads a CSV."


def test_no_sql_reason_does_not_excuse_a_write() -> None:
    with pytest.raises(UnsafeSqlError):
        ReadOnlySql.parse("-- No SQL used: honest\nDROP TABLE t")


def test_query_ids_are_bound_to_the_statement_they_lead() -> None:
    parsed = ReadOnlySql.parse(
        "-- query_id: q-1\nSELECT 1;\n/* query_id: q-2 */ SELECT 2;\n"
    )

    assert parsed.query_ids == {"q-1", "q-2"}


@pytest.mark.parametrize(
    "sql",
    [
        "-- query_id: q-1\n-- No SQL used: comment only\n",
        "SELECT '\n-- query_id: q-1\n' AS note;",
        "SELECT 1;\n-- query_id: q-1\n",
        "SELECT 1 -- query_id: q-1\n, 2;",
    ],
)
def test_query_id_with_no_statement_does_not_count(sql: str) -> None:
    assert ReadOnlySql.parse(sql).query_ids == frozenset()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT $$unterminated",
        "SELECT $a$ unterminated",
        "SELECT 1; $$",
        "SELECT $a$ x $b$",
        "SELECT `open",
        "SELECT 'open",
        'SELECT "open',
        "SELECT [open",
        "SELECT 1 /* open",
        "/* only open",
    ],
)
def test_unterminated_forms_are_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        ReadOnlySql.parse(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT $$closed$$",
        "SELECT $a$ closed $a$",
        "SELECT `closed` FROM t",
        "SELECT $1",
        "SELECT a$b$c FROM t",
        "SELECT '$$' AS note",
    ],
)
def test_closed_dollar_and_backtick_forms_stay_allowed(sql: str) -> None:
    assert ReadOnlySql.parse(sql).statement_count == 1
