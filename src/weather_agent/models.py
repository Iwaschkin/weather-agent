"""Typed value objects for open-meteo geocoding and forecast data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    """A single geocoding match for a place name.

    Attributes:
        name: The resolved place name as returned by the geocoding API.
        country: The country the place belongs to, or an empty string when the
            API omits it.
        country_code: ISO-3166 alpha-2 country code (for example ``"GB"``), or an
            empty string when the API omits it. Used to disambiguate matches.
        admin1: First-level administrative region (for example ``"England"`` or a
            US state), or an empty string when the API omits it.
        population: Reported population, or ``None`` when unknown. Used to rank
            otherwise-equivalent matches so larger places win ties.
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        timezone: IANA timezone name for the place (for example ``"Asia/Tokyo"``),
            or an empty string when the API omits it.
    """

    name: str
    country: str
    country_code: str
    admin1: str
    population: int | None
    latitude: float
    longitude: float
    timezone: str = ""


@dataclass(frozen=True, slots=True)
class CurrentWeather:
    """Current weather conditions reported for a coordinate.

    Temperature and wind are always present; the remaining fields are reported
    only when requested and available, so they are optional and ``None`` when the
    API omits them.

    Attributes:
        time: ISO-8601 timestamp of the observation, as returned by the API.
        temperature_celsius: Air temperature 2 m above ground, in degrees Celsius.
        wind_speed_kmh: Wind speed 10 m above ground, in kilometres per hour.
        weather_code: WMO weather-interpretation code for the condition (for
            example clear, rain, snow), or ``None`` when unavailable.
        relative_humidity_pct: Relative humidity 2 m above ground, in percent.
        dew_point_celsius: Dew point 2 m above ground, in degrees Celsius.
        surface_pressure_hpa: Surface air pressure, in hectopascals.
        cloud_cover_pct: Total cloud cover, in percent.
    """

    time: str
    temperature_celsius: float
    wind_speed_kmh: float
    weather_code: float | None
    relative_humidity_pct: float | None
    dew_point_celsius: float | None
    surface_pressure_hpa: float | None
    cloud_cover_pct: float | None


@dataclass(frozen=True, slots=True)
class TimeSeries:
    """A column-oriented time series shared across open-meteo time-based APIs.

    Open-meteo's forecast, archive, climate, air-quality, marine, flood, and
    ensemble APIs all return the same column-oriented block: a ``time`` array
    plus one parallel array per requested variable. This value object captures
    that shape once so every endpoint can reuse a single parser. Missing samples
    are represented as ``None`` because open-meteo emits JSON ``null`` for gaps.

    Attributes:
        timestamps: ISO-8601 timestamps, one per row, as returned by the API.
        series: Mapping of variable name (for example ``"temperature_2m"``) to a
            column of values aligned with ``timestamps``.
    """

    timestamps: tuple[str, ...]
    series: Mapping[str, tuple[float | None, ...]]

    def column(self, variable: str) -> tuple[float | None, ...]:
        """Return the value column for a variable.

        Args:
            variable: The variable name to fetch, for example ``"temperature_2m"``.

        Returns:
            The column of values aligned with :attr:`timestamps`.

        Raises:
            KeyError: If the variable is not present in this series.
        """
        return self.series[variable]


@dataclass(frozen=True, slots=True)
class CurrentReadings:
    """Current-hour scalar readings for a set of variables at a coordinate.

    Open-meteo's air-quality and marine APIs expose a ``current`` block - a single
    timestamp plus one scalar per requested variable - which reports the present
    hour. This is distinct from an hourly :class:`TimeSeries`, whose first row is
    the start of the day rather than "now".

    Attributes:
        time: ISO-8601 timestamp of the reading, as returned by the API.
        values: Mapping of variable name to its current value, with ``None`` where
            the API reports a gap.
    """

    time: str
    values: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class DayAlmanac:
    """Sun times for a single day at a coordinate.

    Sunrise and sunset are ISO-8601 local datetimes (strings, as the API returns
    them), so they are kept as text rather than forced through the numeric time
    series. ``daylight_seconds`` is numeric.

    Attributes:
        date: The ISO-8601 calendar date (``YYYY-MM-DD``).
        sunrise: ISO-8601 local sunrise timestamp, or an empty string when absent.
        sunset: ISO-8601 local sunset timestamp, or an empty string when absent.
        daylight_seconds: Total daylight for the day, in seconds, or ``None`` when
            unavailable.
    """

    date: str
    sunrise: str
    sunset: str
    daylight_seconds: float | None


@dataclass(frozen=True, slots=True)
class UvIndex:
    """Ultraviolet index for a coordinate: the value now and today's peak.

    Attributes:
        time: ISO-8601 timestamp of the current reading, as returned by the API.
        current: The UV index right now, or ``None`` when unavailable.
        today_max: The maximum UV index forecast for today, or ``None`` when
            unavailable. Used to warn about peak exposure even when it is mild now.
    """

    time: str
    current: float | None
    today_max: float | None


@dataclass(frozen=True, slots=True)
class HistoricalRequest:
    """Parameters for an open-meteo Archive (ERA5) daily query.

    Grouped into a value object so the client method stays within the project's
    argument cap and so callers construct a single validated request.

    Attributes:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``); ERA5 covers
            from 1940 onwards.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        daily: Comma-separated daily variable list, for example
            ``"temperature_2m_max,precipitation_sum"``.
    """

    latitude: float
    longitude: float
    start_date: str
    end_date: str
    daily: str


@dataclass(frozen=True, slots=True)
class ClimateRequest:
    """Parameters for an open-meteo Climate (CMIP6) daily projection query.

    Attributes:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``), up to 2050.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        daily: Comma-separated daily variable list.
        models: Comma-separated CMIP6 model list, for example
            ``"EC_Earth3P_HR"``.
    """

    latitude: float
    longitude: float
    start_date: str
    end_date: str
    daily: str
    models: str


@dataclass(frozen=True, slots=True)
class Elevation:
    """Terrain elevation for a coordinate.

    Attributes:
        meters: Elevation above mean sea level, in metres.
    """

    meters: float


@dataclass(frozen=True, slots=True)
class DroneFlightHour:
    """Weather metrics for a single forecast hour, relevant to drone flight.

    A pure value object: every field is the validated value for one hour, with
    ``None`` where the model did not report a variable. ``wind_max_0_500m_kmh`` is
    derived (not a raw API field): the strongest wind encountered between the
    surface and 500 m above ground level, combining the surface gust, the
    fixed-height winds (10/80/120/180 m), and pressure-level winds whose
    geopotential height falls within the 0-500 m AGL band.

    Attributes:
        time: ISO-8601 local timestamp for the hour.
        temperature_c: Air temperature 2 m above ground, in degrees Celsius.
        apparent_temperature_c: "Feels like" temperature, in degrees Celsius.
        wind_gust_10m_kmh: Surface wind gust 10 m above ground, in km/h.
        wind_max_0_500m_kmh: Derived worst wind across 0-500 m AGL, in km/h.
        precipitation_mm: Total precipitation for the hour, in millimetres.
        precipitation_probability_pct: Probability of precipitation, in percent.
        visibility_m: Horizontal visibility, in metres.
        cape: Convective available potential energy, in J/kg (storm potential).
        freezing_level_agl_m: Height of the 0 degC isotherm above ground level, in
            metres; negative when the air at the surface is already below freezing.
        is_day: Whether the hour is in daylight, or ``None`` when unknown.
        cloud_cover_low_pct: Low-cloud cover, in percent; a high value can mean a
            cloud base low enough to crowd the 120 m ceiling or visual line of
            sight, or ``None`` when unknown.
    """

    time: str
    temperature_c: float | None
    apparent_temperature_c: float | None
    wind_gust_10m_kmh: float | None
    wind_max_0_500m_kmh: float | None
    precipitation_mm: float | None
    precipitation_probability_pct: float | None
    visibility_m: float | None
    cape: float | None
    freezing_level_agl_m: float | None
    is_day: bool | None
    cloud_cover_low_pct: float | None


@dataclass(frozen=True, slots=True)
class DroneForecast:
    """A drone-relevant hourly forecast for a coordinate.

    Attributes:
        elevation_m: Model grid surface elevation above sea level, in metres,
            used to convert pressure-level geopotential heights to AGL.
        hours: Per-hour flight metrics in chronological order.
    """

    elevation_m: float
    hours: tuple[DroneFlightHour, ...]


@dataclass(frozen=True, slots=True)
class DroneProfile:
    """Flight-relevant limits for a specific drone model.

    Wind thresholds are gust speeds in metres per second (matching DJI's
    published wind-resistance ratings). ``caution_gust_ms`` is the manufacturer
    rating; gusts above it are treated as no-fly.

    Attributes:
        key: Short identifier, for example ``"neo"``.
        name: Human-readable model name, for example ``"DJI Neo"``.
        weight_g: Take-off weight in grams (affects UK CAA category).
        ideal_gust_ms: Gust speed below which conditions are ideal.
        caution_gust_ms: Manufacturer wind rating; above it is no-fly.
        min_temp_c: Minimum operating temperature in degrees Celsius.
        max_temp_c: Maximum operating temperature in degrees Celsius.
        is_fpv: Whether the drone is flown FPV (less forgiving in gusts).
        has_omni_sensing: Whether it has omnidirectional obstacle sensing.
        low_light_capable: Whether it tolerates low light (for example LiDAR).
    """

    key: str
    name: str
    weight_g: float
    ideal_gust_ms: float
    caution_gust_ms: float
    min_temp_c: float
    max_temp_c: float
    is_fpv: bool
    has_omni_sensing: bool
    low_light_capable: bool


@dataclass(frozen=True, slots=True)
class CloudLayer:
    """A single reported cloud layer from a METAR.

    Attributes:
        cover: The coverage abbreviation (for example ``"FEW"``, ``"BKN"``,
            ``"OVC"``).
        base_ft_agl: Layer base height above ground level, in feet, or ``None``
            when the report omits a base (for example for clear skies).
    """

    cover: str
    base_ft_agl: float | None


@dataclass(frozen=True, slots=True)
class MetarReport:
    """A decoded METAR observation from the nearest reporting station.

    Provides observed conditions (a reality check against the model forecast) near
    a site. ``ceiling_ft_agl`` is derived: the lowest broken/overcast layer base,
    which is the operative cloud ceiling.

    Attributes:
        station: ICAO station identifier (for example ``"EGCC"``).
        latitude: Station latitude in decimal degrees.
        longitude: Station longitude in decimal degrees.
        observed: Observation time as reported by the API.
        wind_dir_deg: Wind direction in degrees, or ``None`` when variable/calm.
        wind_speed_kt: Sustained wind speed in knots, or ``None`` when unknown.
        wind_gust_kt: Gust speed in knots, or ``None`` when none reported.
        visibility_sm: Horizontal visibility in statute miles, or ``None``.
        clouds: Reported cloud layers in ascending order.
        ceiling_ft_agl: Lowest broken/overcast base in feet AGL, or ``None`` when
            no ceiling (clear or only few/scattered).
        raw: The raw METAR text.
    """

    station: str
    latitude: float
    longitude: float
    observed: str
    wind_dir_deg: float | None
    wind_speed_kt: float | None
    wind_gust_kt: float | None
    visibility_sm: float | None
    clouds: tuple[CloudLayer, ...]
    ceiling_ft_agl: float | None
    raw: str


@dataclass(frozen=True, slots=True)
class TafReport:
    """A nearest-airfield TAF (Terminal Aerodrome Forecast).

    The aviation *forecast* counterpart to :class:`MetarReport`'s observation: an
    independent forecast for the nearest reporting airfield, useful as a cross-check
    against the model's gridded forecast. Only the header fields are decoded; the
    full validity window and change groups stay in ``raw`` for the operator to read.

    Attributes:
        station: ICAO station identifier (for example ``"EGCC"``).
        latitude: Station latitude in decimal degrees.
        longitude: Station longitude in decimal degrees.
        issued: Issue time as reported by the API, or an empty string.
        raw: The raw TAF text (includes the validity period and change groups).
    """

    station: str
    latitude: float
    longitude: float
    issued: str
    raw: str


@dataclass(frozen=True, slots=True)
class Airspace:
    """A nearby airspace volume from OpenAIP (decision support, not authoritative).

    Attributes:
        name: The airspace name (for example ``"MANCHESTER CTR"``).
        type_label: Human-readable airspace type (for example ``"CTR"``,
            ``"Restricted"``), mapped from OpenAIP's numeric type code.
        icao_class: ICAO airspace class letter (for example ``"D"``), or an empty
            string when unclassified or unknown.
        lower_limit: Human-readable lower vertical limit (for example
            ``"GND"`` or ``"1500 ft MSL"``), or an empty string when unknown.
    """

    name: str
    type_label: str
    icao_class: str
    lower_limit: str


class Verdict(Enum):
    """A flyability verdict for a single forecast hour.

    Attributes:
        GOOD: Conditions are within comfortable limits.
        MARGINAL: Flyable with caution; at least one factor is borderline.
        NO_FLY: At least one factor exceeds a safe or legal limit.
    """

    GOOD = "good"
    MARGINAL = "marginal"
    NO_FLY = "no_fly"


class DataConfidence(Enum):
    """How complete and certain an hour's safety-critical inputs were.

    A separate axis from :class:`Verdict`: the verdict says *how flyable*, this says
    *how sure*. They are independent - a ``MARGINAL`` hour may be ``ADEQUATE`` (a
    real borderline) or ``INSUFFICIENT`` (capped at marginal because data was
    missing), and a reader should treat those differently.

    Attributes:
        ADEQUATE: Every safety-critical input was present.
        DEGRADED: Inputs were present but uncertain (e.g. wide ensemble spread).
        INSUFFICIENT: A safety-critical input was missing, so the hour could not be
            certified and was capped at ``MARGINAL`` rather than read as ``GOOD``.
    """

    ADEQUATE = "adequate"
    DEGRADED = "degraded"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class GateReading:
    """One weather gate's structured judgment for an hour.

    Carries the raw value alongside the threshold it was judged against and the
    precomputed ``ratio`` (value / threshold), so a model can read the judgment
    rather than do the comparison itself. ``reason`` is the human string (the
    small-model fallback and the rendered explanation); fields are ``None`` where
    they do not apply (for example a boolean night check has no numeric value).

    Attributes:
        metric: Short metric key, for example ``"wind_gust"`` or ``"cape"``.
        band: This gate's verdict.
        reason: Human-readable explanation; empty when the gate is ``GOOD``.
        value: The metric's value for the hour, or ``None`` when unavailable.
        unit: The value's unit (for example ``"m/s"``, ``"%"``), or empty.
        threshold: The limit the value was judged against, or ``None``.
        limiting: Whether this gate set (tied for) the hour's overall verdict.
        data_missing: Whether this gate degraded because its safety-critical input
            was absent (rather than because a present value was out of limits).
        ratio: ``value / threshold`` when both are present and the threshold is
            non-zero, else ``None`` (a computed property, so the model never
            divides itself).
    """

    metric: str
    band: Verdict
    reason: str = ""
    value: float | None = None
    unit: str = ""
    threshold: float | None = None
    limiting: bool = False
    data_missing: bool = False

    @property
    def ratio(self) -> float | None:
        """``value / threshold`` when both are present and the threshold is non-zero."""
        if self.value is None or self.threshold is None or self.threshold == 0:
            return None
        return self.value / self.threshold


@dataclass(frozen=True, slots=True)
class HourAssessment:
    """The flyability verdict for one forecast hour and one drone.

    Attributes:
        time: ISO-8601 local timestamp for the hour.
        verdict: The overall verdict (the worst of all evaluated gates).
        limiting_factors: Short reasons that produced the verdict; empty when
            the verdict is :attr:`Verdict.GOOD`.
        governing_wind_ms: The worst-case wind used for the wind gate, in metres
            per second, or ``None`` when wind data was unavailable.
        readings: Every gate's structured judgment for the hour, in evaluation
            order (raw value, threshold, ratio, band), for explanation and edge
            reasoning beyond the flat ``limiting_factors`` strings.
        data_confidence: How complete the hour's safety-critical inputs were,
            independent of the verdict.
    """

    time: str
    verdict: Verdict
    limiting_factors: tuple[str, ...]
    governing_wind_ms: float | None
    readings: tuple[GateReading, ...] = ()
    data_confidence: DataConfidence = DataConfidence.ADEQUATE


@dataclass(frozen=True, slots=True)
class FlightWindow:
    """A contiguous run of good-to-fly hours.

    Attributes:
        start_time: ISO-8601 timestamp of the first good hour.
        end_time: ISO-8601 timestamp of the last good hour.
        hours: Number of consecutive good hours.
    """

    start_time: str
    end_time: str
    hours: int


@dataclass(frozen=True, slots=True)
class DayOutlook:
    """A one-line flyability outlook for a single calendar day.

    Attributes:
        date: The ISO-8601 calendar date (``YYYY-MM-DD``).
        good_hours: Number of good-to-fly hours that day.
        best_window: The best contiguous good window that day, or ``None`` when no
            hour was good.
    """

    date: str
    good_hours: int
    best_window: FlightWindow | None


@dataclass(frozen=True, slots=True)
class DroneAssessment:
    """A full per-hour flyability assessment for one drone at one place.

    Attributes:
        drone_name: The assessed drone's display name.
        place_label: Human-readable location the assessment is for.
        hours: Per-hour verdicts in chronological order.
        best_window: The best contiguous good-to-fly window, or ``None`` when no
            hour was good.
        daily: A per-day outlook over the assessment window (empty when the window
            is empty), so multi-day forecasts can be skimmed day by day.
    """

    drone_name: str
    place_label: str
    hours: tuple[HourAssessment, ...]
    best_window: FlightWindow | None
    daily: tuple[DayOutlook, ...] = ()


@dataclass(frozen=True, slots=True)
class SiteBriefing:
    """Optional environmental context shown alongside a drone assessment.

    Bundles the non-forecast briefing items (sun times, observed aviation weather,
    nearby airspace) so the report renderer takes one context object rather than a
    long parameter list. All fields are optional and default to "absent".

    Attributes:
        sun_times: Daily sun times; today's sunrise/sunset frame the daylight
            window.
        metar: The nearest station's observed conditions, or ``None`` when none was
            found or the lookup failed.
        airspace: Nearby drone-relevant airspace volumes to verify before flying.
        airspace_note: A short status line when airspace could not be checked (for
            example no API key configured), or an empty string.
        metar_vs_forecast: A one-line observed-vs-forecast reconciliation note, or
            an empty string when there is no METAR or nothing comparable.
    """

    sun_times: tuple[DayAlmanac, ...] = ()
    metar: MetarReport | None = None
    airspace: tuple[Airspace, ...] = ()
    airspace_note: str = ""
    metar_vs_forecast: str = ""


@dataclass(frozen=True, slots=True)
class CaaGuidance:
    """UK CAA operational guidance for a specific drone (not legal advice).

    Attributes:
        drone_name: The drone the guidance applies to.
        uk_class_label: UK class marking and weight band, for example
            ``"C0 (sub-250 g)"``.
        subcategory: Open-category subcategory the drone can fly in, for example
            ``"A1"``.
        height_limit_note: The 120 m height rule and the terrain/obstacle clause.
        key_rules: Short universal operating rules.
        class_caveat: A model-specific caveat (for example a heavier battery
            changing the class), or an empty string when none applies.
        disclaimer: A standing reminder that this is decision support, not legal
            or airworthiness authority.
    """

    drone_name: str
    uk_class_label: str
    subcategory: str
    height_limit_note: str
    key_rules: tuple[str, ...]
    class_caveat: str
    disclaimer: str


@dataclass(frozen=True, slots=True)
class FleetMember:
    """One drone paired with its flyability assessment and CAA guidance.

    Bundles the three per-drone artifacts the fleet renderer needs so it can show
    every drone at one site side by side without parallel-list bookkeeping.

    Attributes:
        profile: The drone's specification (name, wind limit, weight).
        assessment: The per-hour flyability assessment for this drone.
        guidance: UK CAA guidance for this drone's class.
    """

    profile: DroneProfile
    assessment: DroneAssessment
    guidance: CaaGuidance


@dataclass(frozen=True, slots=True)
class FleetAssessment:
    """The structured result of assessing every drone at one location.

    The typed counterpart to the rendered fleet report: it carries the per-drone
    assessments and the shared site briefing so a caller (for example a UI) can draw
    its own output instead of parsing text.

    Attributes:
        place_label: Human-readable location the assessment is for.
        members: One :class:`FleetMember` per supported drone, sharing one forecast.
        briefing: Shared site context (sun times, METAR, airspace).
    """

    place_label: str
    members: tuple[FleetMember, ...]
    briefing: SiteBriefing


@dataclass(frozen=True, slots=True)
class KpIndex:
    """The latest planetary K-index (geomagnetic activity).

    Kp ranges from 0 (quiet) to 9 (extreme storm). Values of 5 or more indicate a
    geomagnetic storm that can degrade GNSS accuracy and disturb drone compasses.

    Attributes:
        time: Timestamp of the observation as reported by NOAA SWPC.
        kp: The planetary K-index value.
    """

    time: str
    kp: float


@dataclass(frozen=True, slots=True)
class KpForecastEntry:
    """A single predicted planetary K-index value for a future 3-hour bucket.

    Attributes:
        time: NOAA SWPC timestamp for the bucket, in UTC.
        kp: The predicted planetary K-index for that bucket.
    """

    time: str
    kp: float
