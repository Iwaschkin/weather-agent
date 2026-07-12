"""Typed value objects for open-meteo geocoding and forecast data."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date, datetime

_MIN_LATITUDE = -90.0
_MAX_LATITUDE = 90.0
_MIN_LONGITUDE = -180.0
_MAX_LONGITUDE = 180.0


@dataclass(frozen=True, slots=True)
class Coordinates:
    """Validated WGS84 latitude and longitude used at every spatial boundary.

    Values must be finite, with latitude in ``[-90, 90]`` and longitude in
    ``[-180, 180]``. Construction is the single validation point shared by
    geocoding, weather, aviation, airspace, and elevation calls.
    """

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """Reject non-finite or out-of-range coordinate pairs."""
        if not math.isfinite(self.latitude) or not _MIN_LATITUDE <= self.latitude <= _MAX_LATITUDE:
            message = "latitude must be finite and between -90 and 90"
            raise ValueError(message)
        if (
            not math.isfinite(self.longitude)
            or not _MIN_LONGITUDE <= self.longitude <= _MAX_LONGITUDE
        ):
            message = "longitude must be finite and between -180 and 180"
            raise ValueError(message)


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
        coordinates: Validated WGS84 coordinate pair.
        timezone: IANA time-zone name for the resolved place.
    """

    name: str
    country: str
    country_code: str
    admin1: str
    population: int | None
    coordinates: Coordinates
    timezone: str


@dataclass(frozen=True, slots=True)
class TimeContext:
    """Provider-reported local-time metadata for one Open-Meteo response.

    Attributes:
        timezone: IANA time-zone name resolved for the requested coordinates.
        abbreviation: Provider-supplied short zone label at response time.
        utc_offset_seconds: Provider-supplied applied offset from UTC in seconds.
            This is retained as response metadata; instant conversion uses the
            IANA zone and Unix timestamps so daylight-saving changes are not
            reconstructed from one fixed offset.
    """

    timezone: str
    abbreviation: str
    utc_offset_seconds: int


@dataclass(frozen=True, slots=True)
class CurrentWeather:
    """Current weather conditions reported for a coordinate.

    Temperature and wind are always present; the remaining fields are reported
    only when requested and available, so they are optional and ``None`` when the
    API omits them.

    Attributes:
        time: Aware local timestamp of the observation.
        time_context: Provider-reported time-zone metadata.
        temperature_celsius: Air temperature 2 m above ground, in degrees Celsius.
        wind_speed_kmh: Wind speed 10 m above ground, in kilometres per hour.
        weather_code: WMO weather-interpretation code for the condition (for
            example clear, rain, snow), or ``None`` when unavailable.
        relative_humidity_pct: Relative humidity 2 m above ground, in percent.
        dew_point_celsius: Dew point 2 m above ground, in degrees Celsius.
        surface_pressure_hpa: Surface air pressure, in hectopascals.
        cloud_cover_pct: Total cloud cover, in percent.
    """

    time: datetime
    time_context: TimeContext
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
        timestamps: Aware datetimes for instant-based rows or calendar dates for
            daily rows, one per row.
        time_context: Provider-reported time-zone metadata.
        series: Mapping of variable name (for example ``"temperature_2m"``) to a
            column of values aligned with ``timestamps``.
    """

    timestamps: tuple[date | datetime, ...]
    series: Mapping[str, tuple[float | None, ...]]
    time_context: TimeContext

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
        time: Aware local timestamp of the reading.
        time_context: Provider-reported time-zone metadata.
        values: Mapping of variable name to its current value, with ``None`` where
            the API reports a gap.
    """

    time: datetime
    values: Mapping[str, float | None]
    time_context: TimeContext


@dataclass(frozen=True, slots=True)
class DayAlmanac:
    """Sun times for a single day at a coordinate.

    Sunrise and sunset are aware local instants. ``daylight_seconds`` is numeric.

    Attributes:
        date: The location-local calendar date.
        sunrise: Aware local sunrise timestamp, or ``None`` when absent.
        sunset: Aware local sunset timestamp, or ``None`` when absent.
        daylight_seconds: Total daylight for the day, in seconds, or ``None`` when
            unavailable.
        time_context: Provider-reported time-zone metadata.
    """

    date: date
    sunrise: datetime | None
    sunset: datetime | None
    daylight_seconds: float | None
    time_context: TimeContext


@dataclass(frozen=True, slots=True)
class UvIndex:
    """Ultraviolet index for a coordinate: the value now and today's peak.

    Attributes:
        time: Aware local timestamp of the current reading.
        time_context: Provider-reported time-zone metadata.
        current: The UV index right now, or ``None`` when unavailable.
        today_max: The maximum UV index forecast for today, or ``None`` when
            unavailable. Used to warn about peak exposure even when it is mild now.
    """

    time: datetime
    current: float | None
    today_max: float | None
    time_context: TimeContext


@dataclass(frozen=True, slots=True)
class HistoricalRequest:
    """Parameters for an open-meteo Archive (ERA5) daily query.

    Grouped into a value object so the client method stays within the project's
    argument cap and so callers construct a single validated request.

    Attributes:
        coordinates: Validated WGS84 coordinate pair.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``); ERA5 covers
            from 1940 onwards.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        daily: Comma-separated daily variable list, for example
            ``"temperature_2m_max,precipitation_sum"``.
    """

    coordinates: Coordinates
    start_date: date
    end_date: date
    daily: str


@dataclass(frozen=True, slots=True)
class ClimateRequest:
    """Parameters for an open-meteo Climate (CMIP6) daily projection query.

    Attributes:
        coordinates: Validated WGS84 coordinate pair.
        start_date: Inclusive ISO-8601 start date (``YYYY-MM-DD``), up to 2050.
        end_date: Inclusive ISO-8601 end date (``YYYY-MM-DD``).
        daily: Comma-separated daily variable list.
        models: Comma-separated CMIP6 model list, for example
            ``"EC_Earth3P_HR"``.
    """

    coordinates: Coordinates
    start_date: date
    end_date: date
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
        time: Aware local timestamp for the hour.
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
        unavailable_metrics: Required provider samples that were unavailable for
            this hour. The flyability engine turns this into an explicit unknown
            decision unless a known no-fly condition is also present.
    """

    time: datetime
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
    unavailable_metrics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DroneForecast:
    """A drone-relevant hourly forecast for a coordinate.

    Attributes:
        elevation_m: Model grid surface elevation above sea level, in metres,
            used to convert pressure-level geopotential heights to AGL.
        hours: Per-hour flight metrics in chronological order.
        time_context: Provider-reported time-zone metadata.
    """

    elevation_m: float
    hours: tuple[DroneFlightHour, ...]
    time_context: TimeContext


class RegulatoryMark(Enum):
    """Aircraft conformity status used by the current UK Open Category rules."""

    UK0 = "UK0"
    UK1 = "UK1"
    EU_C0 = "EU C0"
    EU_C1 = "EU C1"
    LEGACY = "legacy/unmarked"


class OpenSubcategory(Enum):
    """UK Open Category subcategory supported by a configured aircraft."""

    A1 = "A1"
    A2 = "A2"
    A3 = "A3"


@dataclass(frozen=True, slots=True)
class DroneProfile:
    """Flight-relevant limits for a specific drone model.

    Wind thresholds are gust speeds in metres per second (matching DJI's
    published wind-resistance ratings). ``caution_gust_ms`` is the manufacturer
    rating; gusts above it are treated as no-fly.

    Attributes:
        key: Short identifier, for example ``"neo"``.
        name: Human-readable model name, for example ``"DJI Neo"``.
        configuration: Exact battery/aircraft configuration represented.
        weight_g: Take-off weight in grams for this configuration.
        regulatory_mark: Actual mark printed for this configuration, never one
            inferred from weight.
        open_subcategory: Current UK Open subcategory supported by that mark.
        mark_valid_until: Last date a transitional EU mark is recognised as its
            corresponding UK mark, or ``None`` for a non-transitional status.
        regulatory_source: Manufacturer source for mass and class-mark facts.
        regulatory_reviewed_as_of: Date those configuration facts were reviewed.
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
    configuration: str
    weight_g: float
    regulatory_mark: RegulatoryMark
    open_subcategory: OpenSubcategory
    mark_valid_until: date | None
    regulatory_source: str
    regulatory_reviewed_as_of: date
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
        coordinates: Validated station coordinate pair.
        observed: Aware UTC observation time.
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
    coordinates: Coordinates
    observed: datetime
    wind_dir_deg: float | None
    wind_speed_kt: float | None
    wind_gust_kt: float | None
    visibility_sm: float | None
    clouds: tuple[CloudLayer, ...]
    ceiling_ft_agl: float | None
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


class SourceState(Enum):
    """Availability state for a supplemental assessment source.

    Supplemental sources add operational context but do not manufacture a
    successful weather gate when absent. ``PARTIAL`` means the source covered
    only part of the requested assessment window.
    """

    AVAILABLE = "available"
    PARTIAL = "partial"
    CURRENT_ONLY = "current_only"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    NOT_CONFIGURED = "not_configured"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """Observed availability of one external source for an assessment.

    Attributes:
        source: Stable source label, for example ``"NOAA Kp"``.
        state: Typed availability state.
        detail: Concise operator-facing context, without response bodies or
            credentials.
    """

    source: str
    state: SourceState
    detail: str = ""


class Verdict(Enum):
    """A flyability verdict for a single forecast hour.

    Attributes:
        GOOD: Conditions are within comfortable limits.
        MARGINAL: Flyable with caution; at least one factor is borderline.
        UNKNOWN: Required weather data is incomplete, so the hour cannot be
            recommended.
        NO_FLY: At least one factor exceeds a safe or legal limit.
    """

    GOOD = "good"
    MARGINAL = "marginal"
    UNKNOWN = "unknown"
    NO_FLY = "no_fly"


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
        time: Aware local timestamp for the hour.
        verdict: The overall verdict (the worst of all evaluated gates).
        limiting_factors: Short reasons that produced the verdict; empty when
            the verdict is :attr:`Verdict.GOOD`.
        governing_wind_ms: The worst-case wind used for the wind gate, in metres
            per second, or ``None`` when wind data was unavailable.
        readings: Every gate's structured judgment for the hour, in evaluation
            order (raw value, threshold, ratio, band), for explanation and edge
            reasoning beyond the flat ``limiting_factors`` strings.
    """

    time: datetime
    verdict: Verdict
    limiting_factors: tuple[str, ...]
    governing_wind_ms: float | None
    readings: tuple[GateReading, ...] = ()


@dataclass(frozen=True, slots=True)
class FlightWindow:
    """A contiguous run of good-to-fly hours.

    Attributes:
        start_time: Aware timestamp of the first good hour.
        end_time: Aware timestamp of the last good hour.
        hours: Number of consecutive good hours.
    """

    start_time: datetime
    end_time: datetime
    hours: int


@dataclass(frozen=True, slots=True)
class DayOutlook:
    """A one-line flyability outlook for a single calendar day.

    Attributes:
        date: The location-local calendar date.
        good_hours: Number of good-to-fly hours that day.
        best_window: The best contiguous good window that day, or ``None`` when no
            hour was good.
    """

    date: date
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
        time_context: Provider-reported time-zone metadata for the forecast.
    """

    drone_name: str
    place_label: str
    hours: tuple[HourAssessment, ...]
    best_window: FlightWindow | None
    time_context: TimeContext
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
        source_statuses: Explicit availability of supplemental sources used for
            the assessment.
    """

    sun_times: tuple[DayAlmanac, ...] = ()
    metar: MetarReport | None = None
    airspace: tuple[Airspace, ...] = ()
    airspace_note: str = ""
    metar_vs_forecast: str = ""
    source_statuses: tuple[SourceStatus, ...] = ()


@dataclass(frozen=True, slots=True)
class CaaGuidance:
    """UK CAA operational guidance for a specific drone (not legal advice).

    Attributes:
        drone_name: The drone the guidance applies to.
        configuration: Exact configured battery/aircraft state.
        jurisdiction: Jurisdiction in which this guidance applies.
        aircraft_class: Explicit aircraft mark and any transition context.
        subcategory: Current Open-category subcategory for the configuration.
        height_limit_note: The 120 m height rule and the terrain/obstacle clause.
        key_rules: Short universal operating rules.
        remote_id_note: Applicable Remote ID date and operating requirement.
        reviewed_as_of: Date the embedded CAA wording was last reviewed.
        source_urls: Current official sources supporting the deterministic text.
        disclaimer: A standing reminder that this is decision support, not legal
            or airworthiness authority.
    """

    drone_name: str
    configuration: str
    jurisdiction: str
    aircraft_class: str
    subcategory: OpenSubcategory
    height_limit_note: str
    key_rules: tuple[str, ...]
    remote_id_note: str
    reviewed_as_of: date
    source_urls: tuple[str, ...]
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
        time: Aware UTC timestamp of the observation.
        kp: The planetary K-index value.
    """

    time: datetime
    kp: float


class KpRowKind(Enum):
    """NOAA classification for a Kp forecast-product row."""

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    PREDICTED = "predicted"


@dataclass(frozen=True, slots=True)
class KpForecastEntry:
    """A single predicted planetary K-index value for a future 3-hour bucket.

    Attributes:
        time: Aware UTC timestamp at the start of the three-hour bucket.
        kp: The planetary K-index for that bucket.
        kind: Whether NOAA marks the row observed, estimated, or predicted.
        noaa_scale: NOAA geomagnetic-storm scale label, or ``None`` when quiet.
    """

    time: datetime
    kp: float
    kind: KpRowKind
    noaa_scale: str | None
