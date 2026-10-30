from __future__ import annotations

import pytest

from agentic_research_loop.sql_safety import first_forbidden_sql_word, sql_code_only


@pytest.mark.parametrize(
    ("sql", "word"),
    [
        ("SELECT 'it\\'s'; DROP TABLE t; -- '", "DROP"),
        ("SELECT $$text$$; DELETE FROM t", "DELETE"),
        ("SELECT SYSTEM$CANCEL_ALL_QUERIES()", "SYSTEM$CANCEL_ALL_QUERIES"),
        ("SELECT seq.NEXTVAL", "NEXTVAL"),
    ],
)
def test_write_hidden_behind_quoting_is_found(sql: str, word: str) -> None:
    assert first_forbidden_sql_word(sql_code_only(sql)) == word


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT $$never closed",
        "SELECT 'never closed",
        'SELECT "SYSTEM$CANCEL_ALL_QUERIES"()',
    ],
)
def test_sql_that_cannot_be_scanned_is_rejected(sql: str) -> None:
    with pytest.raises(ValueError):
        sql_code_only(sql)


def test_quoted_keywords_stay_allowed() -> None:
    assert (
        first_forbidden_sql_word(sql_code_only("SELECT 'DROP TABLE t' AS note")) is None
    )
