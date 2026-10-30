"""Thin read-only wrappers for the Search Console and GA4 Data APIs.

Uses Application Default Credentials (ADC) with auto-refresh. The site and the
property are required configuration, so the code carries no account values.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

import google.auth
import google.auth.credentials
import google.auth.exceptions
import google.auth.transport.requests

_GSC_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
_GA4_BASE = "https://analyticsdata.googleapis.com/v1beta"

_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]

# Add `--client-id-file=<your-oauth-client.json>` when the built-in gcloud client
# is rejected for Search Console; run `research source show gsc`.
_RE_AUTH_COMMAND = (
    "gcloud auth application-default login "
    '--scopes="https://www.googleapis.com/auth/webmasters.readonly,'
    "https://www.googleapis.com/auth/analytics.readonly,"
    'https://www.googleapis.com/auth/cloud-platform"'
)


class GoogleAuthError(RuntimeError):
    """Raised when ADC credentials are missing or cannot be refreshed."""


class GoogleApiError(RuntimeError):
    """Raised when a Google API request fails after authentication succeeds."""


def _load_credentials() -> google.auth.credentials.Credentials:
    try:
        credentials = cast(
            "google.auth.credentials.Credentials",
            google.auth.default(scopes=_SCOPES)[0],  # pyright: ignore[reportUnknownMemberType]
        )
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise GoogleAuthError(
            f"ADC credentials not found: {exc}\n\nRe-authenticate with:\n  {_RE_AUTH_COMMAND}"
        ) from exc
    try:
        credentials.refresh(google.auth.transport.requests.Request())  # pyright: ignore[reportUnknownMemberType]
    except google.auth.exceptions.RefreshError as exc:
        raise GoogleAuthError(
            f"Token refresh failed: {exc}\n\nRe-authenticate with:\n  {_RE_AUTH_COMMAND}"
        ) from exc
    return credentials


def _authed_request(url: str, body: dict[str, Any]) -> dict[str, Any]:
    credentials = _load_credentials()
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }
    quota_project = os.environ.get("GCP_QUOTA_PROJECT") or credentials.quota_project_id
    if quota_project:
        headers["x-goog-user-project"] = quota_project
    request = urllib.request.Request(  # noqa: S310 - both base URLs are https constants
        url, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - same URL
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip() or exc.reason
        raise GoogleApiError(f"Google API request failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise GoogleApiError(f"Google API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise GoogleApiError("Google API request timed out after 30 seconds") from exc
    except json.JSONDecodeError as exc:
        raise GoogleApiError(f"Google API returned invalid JSON: {exc}") from exc


def gsc_query(
    *,
    site: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    row_limit: int = 100,
    start_row: int = 0,
) -> dict[str, Any]:
    """Query the Search Analytics API for a verified site."""
    url = f"{_GSC_BASE}/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query"
    return _authed_request(
        url,
        {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "startRow": start_row,
        },
    )


def ga4_report(
    *,
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    metrics: list[str],
    limit: int = 25,
    offset: int = 0,
    order_by: str | None = None,
) -> dict[str, Any]:
    """Run a GA4 Data API report for a property."""
    url = f"{_GA4_BASE}/properties/{urllib.parse.quote(property_id, safe='')}:runReport"
    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": name} for name in dimensions],
        "metrics": [{"name": name} for name in metrics],
        "limit": limit,
        "offset": offset,
    }
    if order_by:
        body["orderBys"] = [{"metric": {"metricName": order_by}, "desc": True}]
    return _authed_request(url, body)
