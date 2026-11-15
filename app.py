"""METAR Reader: type an airport code, get the weather in plain English.

A small Flask application with a single page. The visitor submits an
airport code, the app fetches that airport's current METAR (a standardized
aviation weather report) from aviationweather.gov, and metar_decoder turns
it into a readable report.

Run locally with:

    python app.py
"""

import re

import requests
from flask import Flask, render_template, request

from metar_decoder import decode

# Public Aviation Weather Center data API. No API key is required.
API_URL = "https://aviationweather.gov/api/data/metar"

# Seconds to wait for the weather service before giving up, so a slow
# upstream response can't hang the page indefinitely.
REQUEST_TIMEOUT = 10

# Airport identifiers are 3 characters (US local/IATA style, e.g. HIO) or
# 4 characters (ICAO, e.g. KHIO). Anything else is rejected before it is
# sent to the weather service.
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")

app = Flask(__name__)


class LookupError_(Exception):
    """A lookup failure whose message is safe to show to the visitor.

    The trailing underscore avoids shadowing Python's built-in LookupError.
    """


def fetch_metar(code):
    """Fetch the latest METAR for one station from aviationweather.gov.

    Args:
        code: Station identifier, already validated and upper-cased.

    Returns:
        A (raw_metar, airport_name) tuple, or (None, None) if the service
        has no report for that station.

    Raises:
        LookupError_: If the weather service can't be reached or returns
            an HTTP error.
    """
    try:
        resp = requests.get(
            API_URL,
            # JSON is requested (rather than the default plain text) because
            # it also carries the airport's name alongside the raw report.
            params={"ids": code, "format": "json"},
            headers={"User-Agent": "metar-reader"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        # Deliberately generic: network details are of no use to the visitor.
        raise LookupError_("Couldn't reach the weather service. Please try again in a moment.")

    # The service answers an unknown station with an empty body, not an
    # error status, so "no data" has to be detected from the content.
    try:
        reports = resp.json() if resp.text.strip() else []
    except ValueError:
        reports = []
    if not reports or not reports[0].get("rawOb"):
        return None, None
    return reports[0]["rawOb"], reports[0].get("name")


def lookup(code):
    """Validate an airport code and return its decoded weather report.

    Args:
        code: The airport code exactly as the visitor typed it.

    Returns:
        The dict produced by metar_decoder.decode(), with the airport's
        name added under the "name" key.

    Raises:
        LookupError_: If the code is malformed, no report exists for it,
            or the weather service is unavailable.
    """
    code = code.strip().upper()
    if not CODE_RE.match(code):
        raise LookupError_("Airport codes are 3 or 4 letters, like KHIO or EGLL.")

    # US airports are usually known by 3 letters (HIO), but METARs are filed
    # under the 4-letter ICAO code (KHIO). Try the "K" form first, then fall
    # back to the code as typed.
    candidates = [code] if len(code) == 4 else ["K" + code, code]
    for candidate in candidates:
        raw, name = fetch_metar(candidate)
        if raw:
            report = decode(raw)
            report["name"] = name
            return report

    raise LookupError_(
        'No weather report found for "%s". Check the code, or try the '
        "4-letter ICAO version (for example KPDX instead of PDX)." % code
    )


@app.route("/")
def index():
    """Render the search form and, if a code was submitted, its report.

    The code arrives as a query parameter (/?airport=KHIO) rather than a
    POST body, so results can be bookmarked, shared, and refreshed.
    """
    code = request.args.get("airport", "")
    report = error = None
    if code.strip():
        try:
            report = lookup(code)
        except LookupError_ as exc:
            error = str(exc)
    return render_template("index.html", code=code.strip().upper(), report=report, error=error)


if __name__ == "__main__":
    # Development server only. Debug mode enables an interactive debugger
    # that can execute arbitrary code, so never expose it to the internet;
    # use a production WSGI server instead (see README).
    app.run(debug=True)
