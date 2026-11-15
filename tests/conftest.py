"""Shared fixtures and helpers for the METAR Reader tests.

No test talks to the real weather service: `mock_get` replaces the HTTP call
and `service_response` builds the canned replies it returns.
"""

from unittest.mock import Mock, patch

import pytest
import requests

import app as app_module


def service_response(reports=None, text=None, http_error=False):
    """Build a fake `requests` response from the weather service.

    Args:
        reports: List of report dicts the service "returns" as JSON.
        text: Raw body to use instead. If it is not JSON-like, .json()
            raises ValueError, as the real library does.
        http_error: If True, raise_for_status() raises HTTPError.
    """
    resp = Mock()
    if reports is not None:
        resp.text = "[...]" if reports else "[]"
        resp.json.return_value = reports
    else:
        resp.text = text or ""
        resp.json.side_effect = ValueError("not JSON")
    if http_error:
        resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    return resp


def metar_report(raw, name="Test Airport, OR, US"):
    """Build one report dict shaped like the service's JSON."""
    report = {"rawOb": raw}
    if name is not None:
        report["name"] = name
    return report


@pytest.fixture
def mock_get():
    """Replace the HTTP call made by app.py with a mock."""
    with patch.object(app_module.requests, "get") as mocked:
        yield mocked


@pytest.fixture
def client():
    """A Flask test client for requesting pages without a running server."""
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()
