"""Decode a raw METAR weather report into plain English.

The entry point is decode(raw), which returns a dict with a one-line
`summary`, a list of labelled `details`, and the parsed values.
"""

import math
import re
from datetime import datetime, timedelta, timezone

COMPASS = [
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
]

PHENOMENA = {
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains",
    "IC": "ice crystals", "PL": "ice pellets", "GR": "hail",
    "GS": "small hail", "UP": "unknown precipitation",
    "BR": "mist", "FG": "fog", "FU": "smoke", "VA": "volcanic ash",
    "DU": "dust", "SA": "sand", "HZ": "haze", "PY": "spray",
    "PO": "dust whirls", "SQ": "squalls", "FC": "funnel cloud",
    "SS": "sandstorm", "DS": "dust storm",
}

# How each descriptor wraps the phenomenon it modifies.
DESCRIPTORS = {
    "MI": "shallow {}", "PR": "partial {}", "BC": "patches of {}",
    "DR": "low drifting {}", "BL": "blowing {}", "FZ": "freezing {}",
    "SH": "{} showers", "TS": "thunderstorm with {}",
}

CLOUD_COVER = {
    "FEW": "a few clouds", "SCT": "scattered clouds",
    "BKN": "broken clouds", "OVC": "overcast",
}

# Sky wording for the headline, from least to most cloud.
SKY_RANK = ["CLR", "FEW", "SCT", "BKN", "OVC", "VV"]
SKY_HEADLINE = {
    "CLR": "clear skies", "FEW": "mostly clear", "SCT": "partly cloudy",
    "BKN": "mostly cloudy", "OVC": "overcast", "VV": "sky obscured",
}

WIND_RE = re.compile(r"^(\d{3}|VRB|///)(\d{2,3}|//)(?:G(\d{2,3}))?(KT|MPS|KMH)$")
WIND_VAR_RE = re.compile(r"^(\d{3})V(\d{3})$")
TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")
VIS_SM_RE = re.compile(r"^([MP])?(?:(\d+)|(\d+)/(\d+))SM$")
VIS_M_RE = re.compile(r"^(\d{4})(?:NDV)?$")
CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(CB|TCU)?(?:///)?$")
TEMP_RE = re.compile(r"^(M?\d{2})/(M?\d{2}|//)?$")
ALT_RE = re.compile(r"^([AQ])(\d{4})$")
PRECISE_TEMP_RE = re.compile(r"^T([01])(\d{3})([01])(\d{3})$")
WX_RE = re.compile(
    r"^(\+|-|VC)?((?:MI|PR|BC|DR|BL|SH|TS|FZ)*)((?:%s)*)$" % "|".join(PHENOMENA)
)

KT_PER = {"KT": 1.0, "MPS": 1.943844, "KMH": 1 / 1.852}


def compass(degrees):
    return COMPASS[int((degrees % 360) / 22.5 + 0.5) % 16]


def c_to_f(celsius):
    return celsius * 9 / 5 + 32


def _mph(knots):
    return int(round(knots * 1.15078))


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _signed(token):
    return -int(token[1:]) if token.startswith("M") else int(token)


def _decode_weather(token):
    """Turn a weather group such as -RA or +TSRAGR into English, or None."""
    m = WX_RE.match(token)
    if not m or not (m.group(2) or m.group(3)):
        return None
    intensity, descriptors, phenomena = m.groups()
    if token == "+FC":
        return "tornado or waterspout"

    names = [PHENOMENA[phenomena[i:i + 2]] for i in range(0, len(phenomena), 2)]
    text = _join(names)
    for i in range(len(descriptors) - 2, -1, -2):
        code = descriptors[i:i + 2]
        if text:
            text = DESCRIPTORS[code].format(text)
        else:
            text = {"TS": "thunderstorm", "SH": "showers"}.get(code, "")
    if not text:
        return None

    if intensity == "-":
        text = "light " + text
    elif intensity == "+":
        text = "heavy " + text
    elif intensity == "VC":
        text += " nearby"
    return text


def _observed_at(day, hour, minute, now):
    """METAR only gives day-of-month, so anchor it to the current month."""
    year, month = now.year, now.month
    for _ in range(3):
        try:
            when = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            when = None  # e.g. day 31 in a 30-day month
        if when and when <= now + timedelta(days=1):
            return when
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return None


def _age(when, now):
    minutes = int((now - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return "%d minute%s ago" % (minutes, "" if minutes == 1 else "s")
    hours = minutes // 60
    if hours < 48:
        return "%d hour%s ago" % (hours, "" if hours == 1 else "s")
    return "%d days ago" % (hours // 24)


def parse(raw, now=None):
    """Parse a raw METAR string into a dict of values (None when absent)."""
    now = now or datetime.now(timezone.utc)
    data = {
        "raw": raw.strip(), "station": None, "observed": None, "automated": False,
        "wind": None, "visibility": None, "weather": [], "clouds": [],
        "sky_clear": False, "temp_c": None, "dewpoint_c": None,
        "pressure_inhg": None, "pressure_hpa": None,
    }

    body, _, remarks = data["raw"].partition(" RMK")
    tokens = body.split()
    while tokens and tokens[0] in ("METAR", "SPECI"):
        tokens.pop(0)
    if tokens:
        data["station"] = tokens.pop(0)

    whole_miles = None  # holds the "1" of a split visibility like "1 1/2SM"
    for i, tok in enumerate(tokens):
        # Trend forecasts follow the observation; they aren't current weather.
        if tok in ("TEMPO", "BECMG", "NOSIG"):
            break

        m = TIME_RE.match(tok)
        if m and data["observed"] is None:
            data["observed"] = _observed_at(*map(int, m.groups()), now=now)
            continue

        if tok == "AUTO":
            data["automated"] = True
            continue

        m = WIND_RE.match(tok)
        if m:
            direction, speed, gust, unit = m.groups()
            if speed != "//":
                factor = KT_PER[unit]
                data["wind"] = {
                    "direction": int(direction) if direction.isdigit() else None,
                    "variable": direction == "VRB",
                    "speed_kt": int(speed) * factor,
                    "gust_kt": int(gust) * factor if gust else None,
                    "varies": None,
                }
            continue

        m = WIND_VAR_RE.match(tok)
        if m and data["wind"]:
            data["wind"]["varies"] = (int(m.group(1)), int(m.group(2)))
            continue

        if tok == "CAVOK":
            data["visibility"] = {"miles": 6.2, "or_more": True, "less_than": False}
            data["sky_clear"] = True
            continue

        # "1 1/2SM" arrives as two tokens: a whole number, then a fraction.
        if (tok.isdigit() and len(tok) <= 2 and i + 1 < len(tokens)
                and re.match(r"^\d+/\d+SM$", tokens[i + 1])):
            whole_miles = int(tok)
            continue

        m = VIS_SM_RE.match(tok)
        if m:
            prefix, whole, num, den = m.groups()
            miles = float(whole) if whole else int(num) / int(den)
            miles += whole_miles or 0
            whole_miles = None
            data["visibility"] = {
                "miles": miles,
                "or_more": prefix == "P" or miles >= 10,
                "less_than": prefix == "M",
            }
            continue

        m = VIS_M_RE.match(tok)
        if m and data["visibility"] is None:
            metres = int(m.group(1))
            data["visibility"] = {
                "miles": metres / 1609.344,
                "or_more": metres == 9999,
                "less_than": False,
            }
            continue

        if tok in ("CLR", "SKC", "NSC", "NCD"):
            data["sky_clear"] = True
            continue

        m = CLOUD_RE.match(tok)
        if m:
            cover, height, kind = m.groups()
            data["clouds"].append({
                "cover": cover,
                "height_ft": int(height) * 100 if height.isdigit() else None,
                "kind": kind,
            })
            continue

        m = TEMP_RE.match(tok)
        if m:
            data["temp_c"] = float(_signed(m.group(1)))
            if m.group(2) and m.group(2) != "//":
                data["dewpoint_c"] = float(_signed(m.group(2)))
            continue

        m = ALT_RE.match(tok)
        if m:
            if m.group(1) == "A":
                data["pressure_inhg"] = int(m.group(2)) / 100
                data["pressure_hpa"] = data["pressure_inhg"] * 33.8639
            else:
                data["pressure_hpa"] = float(m.group(2))
                data["pressure_inhg"] = data["pressure_hpa"] / 33.8639
            continue

        phrase = _decode_weather(tok)
        if phrase:
            data["weather"].append(phrase)

    # US stations report temperature to a tenth of a degree in the remarks.
    for tok in remarks.split():
        m = PRECISE_TEMP_RE.match(tok)
        if m:
            t_sign, t, d_sign, d = m.groups()
            data["temp_c"] = int(t) / 10 * (-1 if t_sign == "1" else 1)
            data["dewpoint_c"] = int(d) / 10 * (-1 if d_sign == "1" else 1)

    return data


def _sky_code(data):
    if not data["clouds"]:
        return "CLR" if data["sky_clear"] else None
    return max((c["cover"] for c in data["clouds"]), key=SKY_RANK.index)


def _wind_text(wind):
    if wind is None:
        return None
    mph = _mph(wind["speed_kt"])
    if mph == 0:
        return "Calm"
    if wind["variable"] or wind["direction"] is None:
        text = "Variable at %d mph" % mph
    else:
        text = "From the %s at %d mph" % (compass(wind["direction"]), mph)
    if wind["gust_kt"]:
        text += ", gusting to %d mph" % _mph(wind["gust_kt"])
    return text


def _visibility_text(vis):
    if vis is None:
        return None
    miles = vis["miles"]
    if miles >= 3 or miles == int(miles):
        amount = "%d" % round(miles)
    else:
        amount = ("%.2f" % miles).rstrip("0").rstrip(".")
    unit = "mile" if amount == "1" else "miles"
    if vis["less_than"]:
        return "Less than %s %s" % (amount, unit)
    if vis["or_more"]:
        return "%s %s or more" % (amount, unit)
    return "%s %s" % (amount, unit)


def _cloud_text(data):
    if not data["clouds"]:
        return "Clear" if data["sky_clear"] else None
    layers = []
    for c in data["clouds"]:
        if c["cover"] == "VV":
            text = "sky obscured"
            if c["height_ft"] is not None:
                text += ", vertical visibility {:,} ft".format(c["height_ft"])
        else:
            text = CLOUD_COVER[c["cover"]]
            if c["height_ft"] is not None:
                text += " at {:,} ft".format(c["height_ft"])
        if c["kind"] == "CB":
            text += " (thunderclouds)"
        elif c["kind"] == "TCU":
            text += " (towering cumulus)"
        layers.append(text)
    text = _join(layers)
    return text[0].upper() + text[1:]


def _humidity(temp_c, dewpoint_c):
    def saturation(t):
        return math.exp(17.625 * t / (243.04 + t))
    return min(100, round(100 * saturation(dewpoint_c) / saturation(temp_c)))


def decode(raw, now=None):
    """Decode a raw METAR into a friendly summary plus labelled details."""
    now = now or datetime.now(timezone.utc)
    data = parse(raw, now)

    # Headline: "Light rain, overcast, 53°F (12°C). Wind from the ... "
    headline = list(data["weather"])
    sky = _sky_code(data)
    if sky:
        headline.append(SKY_HEADLINE[sky])
    if data["temp_c"] is not None:
        headline.append("%d°F (%d°C)" % (round(c_to_f(data["temp_c"])), round(data["temp_c"])))

    sentences = []
    if headline:
        first = ", ".join(headline)
        sentences.append(first[0].upper() + first[1:] + ".")

    wind = _wind_text(data["wind"])
    if wind == "Calm":
        sentences.append("Winds are calm.")
    elif wind:
        sentences.append("Wind " + wind[0].lower() + wind[1:] + ".")

    visibility = _visibility_text(data["visibility"])
    if visibility:
        sentences.append("Visibility %s." % (visibility[0].lower() + visibility[1:]))

    details = []

    def add(label, value):
        if value:
            details.append({"label": label, "value": value})

    if data["temp_c"] is not None:
        add("Temperature", "%d°F (%.1f°C)" % (round(c_to_f(data["temp_c"])), data["temp_c"]))
    if data["weather"]:
        weather = _join(data["weather"])
        add("Weather", weather[0].upper() + weather[1:])
    add("Sky", _cloud_text(data))

    if wind and data["wind"]:
        w = data["wind"]
        if wind != "Calm":
            knots = "%d kt" % round(w["speed_kt"])
            if w["gust_kt"]:
                knots += ", gusts %d kt" % round(w["gust_kt"])
            wind += " (%s)" % knots
        if w["varies"]:
            wind += "; direction varying between %s and %s" % (
                compass(w["varies"][0]), compass(w["varies"][1]))
    add("Wind", wind)
    add("Visibility", visibility)

    if data["dewpoint_c"] is not None:
        add("Dew point", "%d°F (%.1f°C)" % (round(c_to_f(data["dewpoint_c"])), data["dewpoint_c"]))
        if data["temp_c"] is not None:
            add("Humidity", "%d%%" % _humidity(data["temp_c"], data["dewpoint_c"]))
    if data["pressure_inhg"] is not None:
        add("Pressure", "%.2f inHg (%d hPa)" % (data["pressure_inhg"], round(data["pressure_hpa"])))

    if data["observed"]:
        observed = "%s (%s UTC)" % (_age(data["observed"], now),
                                    data["observed"].strftime("%b %d, %H:%M"))
    else:
        observed = None

    data.update(
        summary=" ".join(sentences) or "This report could not be decoded.",
        details=details,
        observed_text=observed,
    )
    return data
