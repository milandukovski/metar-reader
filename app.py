"""METAR Reader: type an airport code, get the weather in plain English."""

import re

import requests
from flask import Flask, render_template, request

from metar_decoder import decode

API_URL = "https://aviationweather.gov/api/data/metar"
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")

app = Flask(__name__)


class LookupError_(Exception):
    """A problem worth showing to the user."""


def fetch_metar(code):
    """Return (raw METAR, airport name) for an airport code."""
    try:
        resp = requests.get(
            API_URL,
            params={"ids": code, "format": "json"},
            headers={"User-Agent": "metar-reader"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        raise LookupError_("Couldn't reach the weather service. Please try again in a moment.")

    # The service answers an unknown station with an empty body.
    try:
        reports = resp.json() if resp.text.strip() else []
    except ValueError:
        reports = []
    if not reports or not reports[0].get("rawOb"):
        return None, None
    return reports[0]["rawOb"], reports[0].get("name")


def lookup(code):
    code = code.strip().upper()
    if not CODE_RE.match(code):
        raise LookupError_("Airport codes are 3 or 4 letters, like KHIO or EGLL.")

    # US airports are usually known by 3 letters (HIO); METAR wants KHIO.
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
    code = request.args.get("airport", "")
    report = error = None
    if code.strip():
        try:
            report = lookup(code)
        except LookupError_ as exc:
            error = str(exc)
    return render_template("index.html", code=code.strip().upper(), report=report, error=error)


if __name__ == "__main__":
    app.run(debug=True)
