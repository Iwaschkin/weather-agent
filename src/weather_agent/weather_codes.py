"""WMO weather-interpretation codes mapped to short human-readable conditions.

Open-meteo reports the current and daily condition as a numeric WMO code
(``weather_code``). This module turns that code into text like "light rain" so
summaries name the condition rather than only temperature and wind. Pure data
plus one lookup; no I/O.
"""

from __future__ import annotations

# WMO 4677 present-weather codes as used by open-meteo, condensed to the buckets
# the API actually emits. See https://open-meteo.com (weather_code variable).
_WMO_DESCRIPTIONS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def describe_weather_code(code: float | None) -> str:
    """Return a short condition phrase for an open-meteo WMO weather code.

    Args:
        code: The numeric ``weather_code`` value (open-meteo emits an integer as a
            JSON number, so it arrives as a float), or ``None`` when unavailable.

    Returns:
        A lower-case condition phrase such as ``"light rain"``; ``"unknown"`` when
        the code is missing, and ``"unknown (code N)"`` for an unrecognised code,
        so an unexpected value is surfaced rather than silently dropped.
    """
    if code is None:
        return "unknown"
    rounded = int(code)
    described = _WMO_DESCRIPTIONS.get(rounded)
    return described if described is not None else f"unknown (code {rounded})"
