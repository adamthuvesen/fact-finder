from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.message import Message
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import google.auth.exceptions
import pytest

from fact_finder.google_api import (
    GoogleApiError,
    GoogleAuthError,
    ga4_report,
    gsc_query,
)


def _mock_urlopen(response_body: dict[str, Any]):
    """Create a mock for urllib.request.urlopen that returns the given response."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read.return_value = json.dumps(response_body).encode()
    return cm


GSC = {
    "site": "https://www.example.com/",
    "start_date": "2026-03-01",
    "end_date": "2026-04-06",
    "dimensions": ["query"],
}


@pytest.fixture(autouse=True)
def _google_env(monkeypatch):
    monkeypatch.setenv("GCP_QUOTA_PROJECT", "example-quota-project")


@pytest.fixture(autouse=True)
def _fake_credentials():
    """Patch google.auth.default to return a fake credential with a valid token."""
    creds = MagicMock()
    creds.token = "fake-token-123"
    with patch(
        "fact_finder.google_api.google.auth.default",
        return_value=(creds, "proj"),
    ):
        yield creds


class TestGscQuery:
    def test_basic_query(self):
        response = {"rows": [{"keys": ["example"], "clicks": 100}]}
        with patch.object(
            urllib.request, "urlopen", return_value=_mock_urlopen(response)
        ) as mock:
            result = gsc_query(**GSC)

            assert result == response
            call_args = mock.call_args[0][0]
            assert call_args.method == "POST"
            assert "searchAnalytics/query" in call_args.full_url
            assert "https%3A%2F%2Fwww.example.com%2F" in call_args.full_url
            body = json.loads(call_args.data)
            assert body["dimensions"] == ["query"]
            assert body["startDate"] == "2026-03-01"
            assert body["rowLimit"] == 100
            assert body["startRow"] == 0

    def test_pagination_params(self):
        with patch.object(
            urllib.request, "urlopen", return_value=_mock_urlopen({})
        ) as mock:
            gsc_query(**GSC, row_limit=50, start_row=200)

            body = json.loads(mock.call_args[0][0].data)
            assert body["rowLimit"] == 50
            assert body["startRow"] == 200

    def test_auth_headers(self):
        with patch.object(
            urllib.request, "urlopen", return_value=_mock_urlopen({})
        ) as mock:
            gsc_query(**GSC)

            req = mock.call_args[0][0]
            assert req.get_header("Authorization") == "Bearer fake-token-123"
            assert req.get_header("X-goog-user-project") == "example-quota-project"


class TestGa4Report:
    def test_report_targets_the_configured_property(self):
        with patch.object(
            urllib.request, "urlopen", return_value=_mock_urlopen({"rows": []})
        ) as mock:
            ga4_report(
                property_id="123456",
                start_date="2026-03-01",
                end_date="2026-04-06",
                dimensions=["date"],
                metrics=["sessions"],
                order_by="sessions",
            )

            request = mock.call_args[0][0]
            assert "/properties/123456:runReport" in request.full_url
            body = json.loads(request.data)
            assert body["metrics"] == [{"name": "sessions"}]
            assert body["orderBys"][0]["metric"]["metricName"] == "sessions"


class TestAuthErrors:
    def test_missing_credentials_raises_google_auth_error(self):
        with (
            patch(
                "fact_finder.google_api.google.auth.default",
                side_effect=google.auth.exceptions.DefaultCredentialsError("not found"),
            ),
            pytest.raises(GoogleAuthError, match="ADC credentials not found"),
        ):
            gsc_query(**GSC)

    def test_refresh_failure_raises_google_auth_error(self, _fake_credentials):
        _fake_credentials.refresh.side_effect = google.auth.exceptions.RefreshError(
            "expired"
        )
        with pytest.raises(GoogleAuthError, match="Token refresh failed"):
            gsc_query(**GSC)


class TestApiErrors:
    def test_http_error_raises_google_api_error(self):
        error_body = b'{"error":{"message":"Invalid dimension"}}'
        http_error = urllib.error.HTTPError(
            url="https://example.test",
            code=400,
            msg="Bad Request",
            hdrs=Message(),
            fp=BytesIO(error_body),
        )

        with (
            patch.object(urllib.request, "urlopen", side_effect=http_error),
            pytest.raises(GoogleApiError, match="400"),
        ):
            gsc_query(**GSC)

    def test_url_error_raises_google_api_error(self):
        with (
            patch.object(
                urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("network down"),
            ),
            pytest.raises(GoogleApiError, match="network down"),
        ):
            gsc_query(**GSC)

    def test_timeout_raises_google_api_error(self):
        with (
            patch.object(urllib.request, "urlopen", side_effect=TimeoutError()),
            pytest.raises(GoogleApiError, match="timed out"),
        ):
            gsc_query(**GSC)

    def test_invalid_json_raises_google_api_error(self):
        response = _mock_urlopen({})
        response.read.return_value = b"<html>not json</html>"
        with (
            patch.object(urllib.request, "urlopen", return_value=response),
            pytest.raises(GoogleApiError, match="invalid JSON"),
        ):
            gsc_query(**GSC)
