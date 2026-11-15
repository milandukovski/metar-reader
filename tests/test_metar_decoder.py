"""Tests that mock METAR readings are interpreted correctly."""

from datetime import datetime, timezone

import pytest

from metar_decoder import compass, decode

# A fixed "current time" so observation ages ("27 minutes ago") are stable.
NOW = datetime(2026, 11, 15, 9, 20, tzinfo=timezone.utc)


def detail(report, label):
    """Return the value of one row in the detail list, or None if absent."""
    for item in report["details"]:
        if item["label"] == label:
            return item["value"]
    return None


def decode_at(raw, now=NOW):
    return decode(raw, now=now)


# --- Full summary sentence -------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    pytest.param(
        "KPDX 150853Z 18004KT 10SM CLR 21/10 A3001",
        "Clear skies, 70°F (21°C). Wind from the south at 5 mph. "
        "Visibility 10 miles or more.",
        id="clear-day",
    ),
    pytest.param(
        "METAR KHIO 150853Z AUTO 15010KT 10SM -RA BKN055 BKN075 OVC095 12/09 "
        "A2966 RMK AO2 SLP043 P0001 60006 T01170094 53010 TSNO",
        "Light rain, overcast, 53°F (12°C). Wind from the south-southeast "
        "at 12 mph. Visibility 10 miles or more.",
        id="light-rain",
    ),
    pytest.param(
        "KJFK 150853Z 00000KT 1 1/2SM +TSRA BR FEW008 BKN015CB OVC030 M02/M05 A2992",
        "Heavy thunderstorm with rain, mist, overcast, 28°F (-2°C). "
        "Winds are calm. Visibility 1.5 miles.",
        id="thunderstorm",
    ),
    pytest.param(
        "SPECI KORD 150853Z VRB03KT M1/4SM FZFG VV002 M10/M11 A3040",
        "Freezing fog, sky obscured, 14°F (-10°C). Wind variable at 3 mph. "
        "Visibility less than 0.25 miles.",
        id="freezing-fog",
    ),
    pytest.param(
        "LFPG 150900Z 27015G28KT CAVOK 18/07 Q1021 NOSIG",
        "Clear skies, 64°F (18°C). Wind from the west at 17 mph, gusting "
        "to 32 mph. Visibility 6 miles or more.",
        id="gusty-cavok",
    ),
])
def test_summary(raw, expected):
    assert decode_at(raw)["summary"] == expected


# --- Wind ------------------------------------------------------------------

@pytest.mark.parametrize("wind, expected", [
    ("00000KT", "Calm"),
    ("36010KT", "From the north at 12 mph (10 kt)"),
    ("VRB03KT", "Variable at 3 mph (3 kt)"),
    ("27015G28KT", "From the west at 17 mph, gusting to 32 mph (15 kt, gusts 28 kt)"),
    ("18005MPS", "From the south at 11 mph (10 kt)"),
    ("09020KMH", "From the east at 12 mph (11 kt)"),
    ("16005KT 120V220",
     "From the south-southeast at 6 mph (5 kt); direction varying between "
     "east-southeast and southwest"),
])
def test_wind(wind, expected):
    report = decode_at("KTST 150853Z %s 10SM CLR 10/05 A3000" % wind)
    assert detail(report, "Wind") == expected


def test_missing_wind_is_omitted():
    report = decode_at("KTST 150853Z /////KT 10SM CLR 10/05 A3000")
    assert detail(report, "Wind") is None
    assert "Wind" not in report["summary"]


@pytest.mark.parametrize("degrees, expected", [
    (0, "north"), (360, "north"), (11, "north"), (12, "north-northeast"),
    (90, "east"), (180, "south"), (225, "southwest"), (270, "west"),
    (349, "north"),
])
def test_compass(degrees, expected):
    assert compass(degrees) == expected


# --- Visibility ------------------------------------------------------------

@pytest.mark.parametrize("visibility, expected", [
    ("10SM", "10 miles or more"),
    ("5SM", "5 miles"),
    ("1SM", "1 mile"),
    ("1 1/2SM", "1.5 miles"),
    ("1/2SM", "0.5 miles"),
    ("M1/4SM", "Less than 0.25 miles"),
    ("P6SM", "6 miles or more"),
    ("0800", "0.5 miles"),          # metres
    ("5000", "3 miles"),            # metres
    ("9999", "6 miles or more"),    # metric "10 km or more"
    ("CAVOK", "6 miles or more"),
])
def test_visibility(visibility, expected):
    report = decode_at("KTST 150853Z 18005KT %s 10/05 A3000" % visibility)
    assert detail(report, "Visibility") == expected


def test_runway_visual_range_is_not_mistaken_for_visibility():
    report = decode_at("UUEE 150853Z 18005MPS 0800 R24L/1200U OVC020 M08/M10 Q1003")
    assert detail(report, "Visibility") == "0.5 miles"


# --- Weather ---------------------------------------------------------------

@pytest.mark.parametrize("weather, expected", [
    ("RA", "Rain"),
    ("-RA", "Light rain"),
    ("+SN", "Heavy snow"),
    ("-DZ", "Light drizzle"),
    ("RASN", "Rain and snow"),
    ("TS", "Thunderstorm"),
    ("+TSRA", "Heavy thunderstorm with rain"),
    ("SHSN", "Snow showers"),
    ("-SHRA", "Light rain showers"),
    ("FZRA", "Freezing rain"),
    ("FZFG", "Freezing fog"),
    ("MIFG", "Shallow fog"),
    ("BCFG", "Patches of fog"),
    ("BLSN", "Blowing snow"),
    ("VCSH", "Showers nearby"),
    ("BR", "Mist"),
    ("HZ", "Haze"),
    ("+FC", "Tornado or waterspout"),
    ("-RA BR", "Light rain and mist"),
])
def test_weather(weather, expected):
    report = decode_at("KTST 150853Z 18005KT 5SM %s OVC020 10/05 A3000" % weather)
    assert detail(report, "Weather") == expected


def test_no_weather_row_when_nothing_is_falling():
    report = decode_at("KTST 150853Z 18005KT 10SM CLR 10/05 A3000")
    assert detail(report, "Weather") is None


# --- Sky -------------------------------------------------------------------

@pytest.mark.parametrize("sky, expected_detail, expected_headline", [
    ("CLR", "Clear", "Clear skies"),
    ("SKC", "Clear", "Clear skies"),
    ("NSC", "Clear", "Clear skies"),
    ("NCD", "Clear", "Clear skies"),
    ("FEW030", "A few clouds at 3,000 ft", "Mostly clear"),
    ("SCT045", "Scattered clouds at 4,500 ft", "Partly cloudy"),
    ("BKN020", "Broken clouds at 2,000 ft", "Mostly cloudy"),
    ("OVC008", "Overcast at 800 ft", "Overcast"),
    ("VV002", "Sky obscured, vertical visibility 200 ft", "Sky obscured"),
    ("BKN015CB", "Broken clouds at 1,500 ft (thunderclouds)", "Mostly cloudy"),
    ("SCT020TCU", "Scattered clouds at 2,000 ft (towering cumulus)", "Partly cloudy"),
    ("FEW010 BKN025 OVC050",
     "A few clouds at 1,000 ft, broken clouds at 2,500 ft and overcast at 5,000 ft",
     "Overcast"),
])
def test_sky(sky, expected_detail, expected_headline):
    report = decode_at("KTST 150853Z 18005KT 10SM %s 10/05 A3000" % sky)
    assert detail(report, "Sky") == expected_detail
    assert report["summary"].startswith(expected_headline + ",")


# --- Temperature, humidity, and pressure -----------------------------------

@pytest.mark.parametrize("group, temperature, dew_point", [
    ("21/10", "70°F (21.0°C)", "50°F (10.0°C)"),
    ("M02/M05", "28°F (-2.0°C)", "23°F (-5.0°C)"),
    ("00/M01", "32°F (0.0°C)", "30°F (-1.0°C)"),
])
def test_temperature_and_dew_point(group, temperature, dew_point):
    report = decode_at("KTST 150853Z 18005KT 10SM CLR %s A3000" % group)
    assert detail(report, "Temperature") == temperature
    assert detail(report, "Dew point") == dew_point


@pytest.mark.parametrize("remark, temperature, dew_point", [
    ("T01170094", "53°F (11.7°C)", "49°F (9.4°C)"),
    ("T10221050", "28°F (-2.2°C)", "23°F (-5.0°C)"),
])
def test_precise_temperature_from_remarks_wins(remark, temperature, dew_point):
    report = decode_at("KTST 150853Z 18005KT 10SM CLR 12/09 A3000 RMK AO2 %s" % remark)
    assert detail(report, "Temperature") == temperature
    assert detail(report, "Dew point") == dew_point


def test_missing_dew_point_omits_dew_point_and_humidity():
    report = decode_at("KTST 150853Z 18005KT 10SM CLR 15/ A3000")
    assert detail(report, "Temperature") == "59°F (15.0°C)"
    assert detail(report, "Dew point") is None
    assert detail(report, "Humidity") is None


@pytest.mark.parametrize("group, humidity", [
    ("10/10", "100%"),
    ("30/20", "55%"),
])
def test_humidity(group, humidity):
    report = decode_at("KTST 150853Z 18005KT 10SM CLR %s A3000" % group)
    assert detail(report, "Humidity") == humidity


@pytest.mark.parametrize("group, expected", [
    ("A2992", "29.92 inHg (1013 hPa)"),
    ("Q1013", "29.91 inHg (1013 hPa)"),
])
def test_pressure(group, expected):
    report = decode_at("KTST 150853Z 18005KT 10SM CLR 10/05 %s" % group)
    assert detail(report, "Pressure") == expected


# --- Station and observation time ------------------------------------------

@pytest.mark.parametrize("raw", [
    "KORD 150853Z 18005KT 10SM CLR 10/05 A3000",
    "METAR KORD 150853Z 18005KT 10SM CLR 10/05 A3000",
    "SPECI KORD 150853Z 18005KT 10SM CLR 10/05 A3000",
])
def test_station_is_read_with_or_without_report_type(raw):
    assert decode_at(raw)["station"] == "KORD"


def test_automated_flag():
    assert decode_at("KTST 150853Z AUTO 18005KT 10SM CLR 10/05 A3000")["automated"] is True
    assert decode_at("KTST 150853Z 18005KT 10SM CLR 10/05 A3000")["automated"] is False


@pytest.mark.parametrize("time_group, expected", [
    ("150920Z", "just now (Nov 15, 09:20 UTC)"),
    ("150919Z", "1 minute ago (Nov 15, 09:19 UTC)"),
    ("150853Z", "27 minutes ago (Nov 15, 08:53 UTC)"),
    ("150819Z", "1 hour ago (Nov 15, 08:19 UTC)"),
    ("150520Z", "4 hours ago (Nov 15, 05:20 UTC)"),
])
def test_observation_age(time_group, expected):
    report = decode_at("KTST %s 18005KT 10SM CLR 10/05 A3000" % time_group)
    assert report["observed_text"] == expected


def test_observation_from_previous_month():
    """A report from the 30th, read just after midnight on the 1st."""
    now = datetime(2026, 12, 1, 0, 10, tzinfo=timezone.utc)
    report = decode_at("KTST 302350Z 18005KT 10SM CLR 10/05 A3000", now=now)
    assert report["observed_text"] == "20 minutes ago (Nov 30, 23:50 UTC)"


# --- Edge cases ------------------------------------------------------------

@pytest.mark.parametrize("trend", ["TEMPO RA", "BECMG 3000 +SN OVC005"])
def test_trend_forecast_is_not_reported_as_current_weather(trend):
    report = decode_at("EGLL 150850Z 16005KT 9999 NCD 05/04 Q1000 %s" % trend)
    assert detail(report, "Weather") is None
    assert detail(report, "Sky") == "Clear"
    assert detail(report, "Visibility") == "6 miles or more"


def test_remarks_are_not_decoded_as_weather():
    report = decode_at("KTST 150853Z 18005KT 10SM CLR 10/05 A3000 RMK AO2 RA BR OVC010")
    assert detail(report, "Weather") is None
    assert detail(report, "Sky") == "Clear"


@pytest.mark.parametrize("raw", ["KXYZ 150853Z AUTO", "KXYZ", ""])
def test_report_with_no_weather_data(raw):
    report = decode_at(raw)
    assert report["summary"] == "This report could not be decoded."
    assert report["details"] == []


def test_raw_report_is_kept_and_trimmed():
    report = decode_at("  KTST 150853Z 18005KT 10SM CLR 10/05 A3000\n")
    assert report["raw"] == "KTST 150853Z 18005KT 10SM CLR 10/05 A3000"
