"""Tests for app.py, with the weather service replaced by a mock."""

import pytest
import requests

import app as app_module
from app import LookupError_, fetch_metar, lookup
from conftest import metar_report, service_response

CLEAR_DAY = "KPDX 150853Z 18004KT 10SM CLR 21/10 A3001"
CLEAR_DAY_SUMMARY = (
    "Clear skies, 70°F (21°C). Wind from the south at 5 mph. "
    "Visibility 10 miles or more."
)


def requested_ids(mock_get):
    """The station codes sent to the service, in call order."""
    return [call.kwargs["params"]["ids"] for call in mock_get.call_args_list]


# --- fetch_metar -----------------------------------------------------------

def test_fetch_returns_raw_report_and_airport_name(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY, "Portland Intl, OR, US")])

    assert fetch_metar("KPDX") == (CLEAR_DAY, "Portland Intl, OR, US")


def test_fetch_calls_the_service_correctly(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY)])

    fetch_metar("KPDX")

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args == (app_module.API_URL,)
    assert kwargs["params"] == {"ids": "KPDX", "format": "json"}
    assert kwargs["timeout"] == app_module.REQUEST_TIMEOUT


def test_fetch_without_airport_name(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY, name=None)])

    assert fetch_metar("KPDX") == (CLEAR_DAY, None)


@pytest.mark.parametrize("response", [
    pytest.param(service_response(text=""), id="empty-body"),
    pytest.param(service_response(text="   \n"), id="blank-body"),
    pytest.param(service_response([]), id="empty-list"),
    pytest.param(service_response(text="<html>oops</html>"), id="not-json"),
    pytest.param(service_response([{"name": "No Report Field"}]), id="no-raw-report"),
])
def test_fetch_returns_nothing_when_service_has_no_report(mock_get, response):
    mock_get.return_value = response

    assert fetch_metar("ZZZZ") == (None, None)


@pytest.mark.parametrize("failure", [
    requests.ConnectionError("no network"),
    requests.Timeout("too slow"),
])
def test_fetch_reports_network_failures(mock_get, failure):
    mock_get.side_effect = failure

    with pytest.raises(LookupError_, match="reach the weather service"):
        fetch_metar("KPDX")


def test_fetch_reports_http_errors(mock_get):
    mock_get.return_value = service_response(text="", http_error=True)

    with pytest.raises(LookupError_, match="reach the weather service"):
        fetch_metar("KPDX")


# --- lookup ----------------------------------------------------------------

def test_lookup_returns_decoded_report(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY, "Portland Intl, OR, US")])

    report = lookup("KPDX")

    assert report["summary"] == CLEAR_DAY_SUMMARY
    assert report["station"] == "KPDX"
    assert report["name"] == "Portland Intl, OR, US"
    assert report["raw"] == CLEAR_DAY


@pytest.mark.parametrize("code", ["", "   ", "AB", "ABCDE", "K-IO", "KH IO", "<b>", "../x"])
def test_lookup_rejects_malformed_codes_without_calling_service(mock_get, code):
    with pytest.raises(LookupError_, match="3 or 4 letters"):
        lookup(code)

    mock_get.assert_not_called()


def test_lookup_trims_and_uppercases_the_code(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY)])

    lookup("  kpdx ")

    assert requested_ids(mock_get) == ["KPDX"]


def test_lookup_tries_us_prefix_for_three_letter_code(mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY)])

    lookup("pdx")

    assert requested_ids(mock_get) == ["KPDX"]


def test_lookup_falls_back_to_three_letter_code_as_typed(mock_get):
    mock_get.side_effect = [
        service_response(text=""),                    # KABC: unknown
        service_response([metar_report(CLEAR_DAY)]),  # ABC: found
    ]

    report = lookup("ABC")

    assert requested_ids(mock_get) == ["KABC", "ABC"]
    assert report["summary"] == CLEAR_DAY_SUMMARY


def test_lookup_four_letter_code_is_not_retried(mock_get):
    mock_get.return_value = service_response(text="")

    with pytest.raises(LookupError_, match='No weather report found for "ZZZZ"'):
        lookup("ZZZZ")

    assert requested_ids(mock_get) == ["ZZZZ"]


def test_lookup_three_letter_code_not_found_anywhere(mock_get):
    mock_get.return_value = service_response(text="")

    with pytest.raises(LookupError_, match='No weather report found for "ABC"'):
        lookup("ABC")

    assert requested_ids(mock_get) == ["KABC", "ABC"]


def test_lookup_passes_on_service_failure(mock_get):
    mock_get.side_effect = requests.ConnectionError("no network")

    with pytest.raises(LookupError_, match="reach the weather service"):
        lookup("KPDX")


# --- The page --------------------------------------------------------------

def page(client, **query):
    resp = client.get("/", query_string=query)
    return resp, resp.get_data(as_text=True)


def test_home_page_shows_only_the_form(client, mock_get):
    resp, body = page(client)

    assert resp.status_code == 200
    assert 'name="airport"' in body
    assert 'class="summary"' not in body
    assert 'role="alert"' not in body
    mock_get.assert_not_called()


def test_blank_code_is_treated_as_no_search(client, mock_get):
    resp, body = page(client, airport="   ")

    assert resp.status_code == 200
    assert 'class="summary"' not in body
    assert 'role="alert"' not in body
    mock_get.assert_not_called()


def test_page_shows_decoded_report(client, mock_get):
    mock_get.return_value = service_response([metar_report(CLEAR_DAY, "Portland Intl, OR, US")])

    resp, body = page(client, airport="kpdx")

    assert resp.status_code == 200
    assert CLEAR_DAY_SUMMARY in body
    assert "Portland Intl, OR, US" in body
    assert CLEAR_DAY in body                 # original METAR is shown
    assert 'value="KPDX"' in body            # code echoed back, upper-cased
    assert 'role="alert"' not in body


def test_page_shows_error_for_unknown_airport(client, mock_get):
    mock_get.return_value = service_response(text="")

    resp, body = page(client, airport="ZZZZ")

    assert resp.status_code == 200
    assert 'role="alert"' in body
    assert "No weather report found" in body
    assert 'class="summary"' not in body


def test_page_shows_error_for_malformed_code(client, mock_get):
    resp, body = page(client, airport="TOOLONG")

    assert 'role="alert"' in body
    assert "3 or 4 letters" in body
    mock_get.assert_not_called()


def test_page_shows_error_when_service_is_down(client, mock_get):
    mock_get.side_effect = requests.Timeout("too slow")

    resp, body = page(client, airport="KPDX")

    assert resp.status_code == 200
    assert 'role="alert"' in body
    assert "reach the weather service" in body


def test_page_escapes_the_submitted_code(client, mock_get):
    resp, body = page(client, airport="<b>")

    assert "<B>" not in body and "<b>" not in body
    assert "&lt;B&gt;" in body


def test_page_escapes_data_from_the_service(client, mock_get):
    mock_get.return_value = service_response(
        [metar_report(CLEAR_DAY, "<script>alert(1)</script>")]
    )

    resp, body = page(client, airport="KPDX")

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
