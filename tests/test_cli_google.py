from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agentic_research_loop.cli import main
from agentic_research_loop.google_api import GoogleApiError

_GSC_RESPONSE = {
    "rows": [
        {
            "keys": ["example"],
            "clicks": 500,
            "impressions": 10000,
            "ctr": 0.05,
            "position": 3.2,
        }
    ]
}


@pytest.fixture(autouse=True)
def _site(monkeypatch):
    monkeypatch.setenv("GSC_SITE", "https://www.example.com/")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456")


class TestGscCli:
    def test_basic_gsc_query(self, capsys):
        with patch(
            "agentic_research_loop.cli.gsc_query", return_value=_GSC_RESPONSE
        ) as mock_gsc:
            exit_code = main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query",
                ]
            )

        assert exit_code == 0
        mock_gsc.assert_called_once_with(
            site="https://www.example.com/",
            start_date="2026-03-01",
            end_date="2026-04-06",
            dimensions=["query"],
            row_limit=100,
            start_row=0,
        )
        output = json.loads(capsys.readouterr().out)
        assert "rows" in output

    def test_gsc_with_pagination(self):
        with patch(
            "agentic_research_loop.cli.gsc_query", return_value=_GSC_RESPONSE
        ) as mock_gsc:
            exit_code = main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query,page",
                    "--row-limit",
                    "50",
                    "--start-row",
                    "200",
                ]
            )

        assert exit_code == 0
        mock_gsc.assert_called_once_with(
            site="https://www.example.com/",
            start_date="2026-03-01",
            end_date="2026-04-06",
            dimensions=["query", "page"],
            row_limit=50,
            start_row=200,
        )

    def test_gsc_missing_required_args(self):
        with pytest.raises(SystemExit) as excinfo:
            main(["gsc", "--start-date", "2026-03-01", "--end-date", "2026-04-06"])
        assert excinfo.value.code == 2

    def test_gsc_rejects_negative_start_row(self):
        with pytest.raises(SystemExit) as excinfo:
            main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query",
                    "--start-row",
                    "-1",
                ]
            )
        assert excinfo.value.code == 2

    def test_gsc_rejects_invalid_date(self):
        with pytest.raises(SystemExit) as excinfo:
            main(
                [
                    "gsc",
                    "--start-date",
                    "2026-02-31",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query",
                ]
            )
        assert excinfo.value.code == 2

    def test_gsc_rejects_inverted_date_range(self, capsys):
        exit_code = main(
            [
                "gsc",
                "--start-date",
                "2026-04-06",
                "--end-date",
                "2026-03-01",
                "--dimensions",
                "query",
            ]
        )
        assert exit_code == 1
        assert "--start-date must be on or before" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("command", "variable"), [("gsc", "GSC_SITE"), ("ga4", "GA4_PROPERTY_ID")]
    )
    def test_site_and_property_have_no_default(
        self, repo_root, monkeypatch, capsys, command, variable
    ):
        """The private repo hardcoded both. A missing value must fail, naming the fix."""
        monkeypatch.chdir(repo_root)
        monkeypatch.delenv(variable)
        extra = ["--metrics", "sessions"] if command == "ga4" else []

        exit_code = main(
            [
                command,
                "--start-date",
                "2026-03-01",
                "--end-date",
                "2026-04-06",
                "--dimensions",
                "date",
                *extra,
            ]
        )

        assert exit_code == 1
        assert variable in capsys.readouterr().err

    def test_site_can_come_from_the_project_table(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.agentic-research-loop]\ngsc_site = "sc-domain:consumer.example"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GSC_SITE")
        with patch(
            "agentic_research_loop.cli.gsc_query", return_value=_GSC_RESPONSE
        ) as mock_gsc:
            main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query",
                ]
            )

        assert mock_gsc.call_args.kwargs["site"] == "sc-domain:consumer.example"

    def test_ga4_passes_the_configured_property(self, capsys):
        with patch(
            "agentic_research_loop.cli.ga4_report", return_value={"rows": []}
        ) as mock_ga4:
            exit_code = main(
                [
                    "ga4",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "date",
                    "--metrics",
                    "sessions",
                ]
            )

        assert exit_code == 0
        assert mock_ga4.call_args.kwargs["property_id"] == "123456"

    def test_gsc_rejects_blank_dimension_token(self):
        with pytest.raises(SystemExit) as excinfo:
            main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query,",
                ]
            )
        assert excinfo.value.code == 2

    def test_gsc_api_errors_are_printed_without_traceback(self, capsys):
        with patch(
            "agentic_research_loop.cli.gsc_query",
            side_effect=GoogleApiError("Google API request failed (400): bad request"),
        ):
            exit_code = main(
                [
                    "gsc",
                    "--start-date",
                    "2026-03-01",
                    "--end-date",
                    "2026-04-06",
                    "--dimensions",
                    "query",
                ]
            )

        assert exit_code == 1
        assert "bad request" in capsys.readouterr().err
