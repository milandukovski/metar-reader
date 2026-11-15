# METAR Reader

A small Flask web app that turns cryptic aviation weather reports into plain English.

Type an airport code, and METAR Reader fetches the airport's current
[METAR](https://en.wikipedia.org/wiki/METAR) from
[aviationweather.gov](https://aviationweather.gov/) and decodes it into
something anyone can read.

**Raw METAR**

```
METAR KHIO 150853Z AUTO 15010KT 10SM -RA BKN055 BKN075 OVC095 12/09 A2966 RMK AO2 SLP043 T01170094
```

**What METAR Reader shows**

> Light rain, overcast, 53°F (12°C). Wind from the south-southeast at 12 mph. Visibility 10 miles or more.

## Features

- One-sentence weather summary in everyday language
- Detail table: temperature, weather, cloud layers, wind, visibility, dew point, humidity, and pressure
- Imperial and metric units side by side (°F/°C, mph/knots, inHg/hPa)
- Works for airports worldwide, including reports in metric units
- Accepts 4-letter ICAO codes (`KHIO`, `EGLL`) and 3-letter US codes (`HIO`)
- Shows how long ago the observation was taken, plus the original METAR
- Light and dark themes that follow your system setting
- No API key or account needed

## Requirements

- Python 3.9 or newer
- An internet connection (weather data is fetched live)

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/milandukovski/metar-reader.git
   cd metar-reader
   ```

2. Create and activate a virtual environment:

   **Windows (PowerShell)**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS / Linux**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Usage

Start the app:

```bash
python app.py
```

Then open <http://127.0.0.1:5000> in your browser, type an airport code, and
press **Get weather**.

You can also link straight to a report: <http://127.0.0.1:5000/?airport=KHIO>

### Airport codes

| You type | What happens |
| --- | --- |
| `KHIO`, `EGLL`, `RJTT` | 4-letter ICAO codes are looked up as-is |
| `HIO`, `PDX`, `JFK` | 3-letter codes are tried with the US `K` prefix first (`KHIO`) |

Airports outside the contiguous United States need their full 4-letter ICAO code.

## Deploying

`python app.py` starts Flask's development server with debug mode on. That is
fine on your own machine but **must not be exposed to the internet**. For a
public deployment, run the app with a production WSGI server, for example:

```bash
# Windows, macOS, or Linux
pip install waitress
waitress-serve --listen=0.0.0.0:8000 app:app
```

```bash
# macOS / Linux
pip install gunicorn
gunicorn --bind 0.0.0.0:8000 app:app
```

## How it works

| File | Purpose |
| --- | --- |
| `app.py` | Flask route, input validation, and the call to the weather service |
| `metar_decoder.py` | Parses the raw METAR and builds the summary and detail list |
| `templates/index.html` | The search form and report page |
| `requirements.txt` | Python dependencies |

The decoder has no dependency on Flask, so it can be used on its own:

```python
from metar_decoder import decode

report = decode("KHIO 150853Z AUTO 15010KT 10SM -RA OVC095 12/09 A2966")
print(report["summary"])
# Light rain, overcast, 54°F (12°C). Wind from the south-southeast at 12 mph. Visibility 10 miles or more.
```

## Running the tests

The test suite uses [pytest](https://docs.pytest.org/). It feeds mock METAR
readings to the decoder and replaces the weather service with a mock, so it
needs no internet connection.

```bash
pip install -r requirements-dev.txt
pytest
```

| File | What it covers |
| --- | --- |
| `tests/test_metar_decoder.py` | Mock METAR readings are turned into the right English |
| `tests/test_app.py` | Fetching, code validation, and the web page, with the service mocked |

## Limitations

- The remarks section (everything after `RMK`) is not translated, apart from
  the precise temperature that US stations report there.
- Trend forecasts (`TEMPO`, `BECMG`) and runway visual range are ignored.
- Wind direction is where the wind is blowing **from**, following the METAR
  convention.
- Not for flight planning. Always use official sources for aviation decisions.

## Data source

Weather data comes from the
[Aviation Weather Center Data API](https://aviationweather.gov/data/api/),
operated by the US National Weather Service.
