"""Interpreted bands for numeric weather metrics ("compute-then-explain").

Hands the model meaning rather than bare numbers: a raw reading is classified into
a labeled band from a published standard, so a small local model does not have to
remember thresholds it reasons about unreliably. This generalizes the UV risk-band
lookup into one seam shared by UV, air quality, and marine conditions.

Each metric maps to a :class:`BandScale` of ascending labeled thresholds. River
discharge is deliberately absent: a meaningful flood band needs a per-river
baseline (return period), not an absolute cut-off, so it stays raw until that
reference exists rather than carry an invented threshold.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BandScale:
    """An ordered set of labeled thresholds for one metric.

    Attributes:
        unit: Display unit for the value (for example ``"µg/m³"``); empty when the
            metric is a unitless index.
        thresholds: Ascending ``(exclusive upper bound, label)`` pairs. A value is
            given the label of the first bound it falls below.
        top_label: Label for values at or above the highest bound.
    """

    unit: str
    thresholds: tuple[tuple[float, str], ...]
    top_label: str


@dataclass(frozen=True, slots=True)
class Metric:
    """A metric's human-facing name and its band scale.

    Attributes:
        name: Display name for the metric (for example ``"PM2.5"``).
        scale: The band scale used to classify the metric's values.
    """

    name: str
    scale: BandScale


def classify(scale: BandScale, value: float) -> str:
    """Return the band label for a value on a scale.

    Args:
        scale: The scale to classify against.
        value: The raw reading.

    Returns:
        The label of the first threshold the value falls below, or the scale's
        ``top_label`` when it is at or above every threshold.
    """
    for upper, label in scale.thresholds:
        if value < upper:
            return label
    return scale.top_label


# WHO ultraviolet index risk bands (the original example, now shared).
UV_SCALE = BandScale(
    unit="",
    thresholds=((3.0, "low"), (6.0, "moderate"), (8.0, "high"), (11.0, "very high")),
    top_label="extreme",
)

# European Air Quality Index bands (EEA). The overall index and each pollutant
# sub-index share the same band names; cut-offs differ per pollutant.
_EUROPEAN_AQI = BandScale(
    unit="",
    thresholds=(
        (20.0, "good"),
        (40.0, "fair"),
        (60.0, "moderate"),
        (80.0, "poor"),
        (100.0, "very poor"),
    ),
    top_label="extremely poor",
)
_PM2_5 = BandScale(
    unit="µg/m³",
    thresholds=(
        (10.0, "good"),
        (20.0, "fair"),
        (25.0, "moderate"),
        (50.0, "poor"),
        (75.0, "very poor"),
    ),
    top_label="extremely poor",
)
_PM10 = BandScale(
    unit="µg/m³",
    thresholds=(
        (20.0, "good"),
        (40.0, "fair"),
        (50.0, "moderate"),
        (100.0, "poor"),
        (150.0, "very poor"),
    ),
    top_label="extremely poor",
)
_OZONE = BandScale(
    unit="µg/m³",
    thresholds=(
        (50.0, "good"),
        (100.0, "fair"),
        (130.0, "moderate"),
        (240.0, "poor"),
        (380.0, "very poor"),
    ),
    top_label="extremely poor",
)

# Significant wave height -> WMO sea-state description.
_WAVE_HEIGHT = BandScale(
    unit="m",
    thresholds=(
        (0.1, "calm"),
        (0.5, "smooth"),
        (1.25, "slight"),
        (2.5, "moderate"),
        (4.0, "rough"),
        (6.0, "very rough"),
        (9.0, "high"),
        (14.0, "very high"),
    ),
    top_label="phenomenal",
)

# Open-meteo variable name -> interpreted metric. Variables without an entry are
# rendered raw (no defensible absolute band, for example wave period).
_METRICS: dict[str, Metric] = {
    "european_aqi": Metric("European AQI", _EUROPEAN_AQI),
    "pm2_5": Metric("PM2.5", _PM2_5),
    "pm10": Metric("PM10", _PM10),
    "ozone": Metric("Ozone", _OZONE),
    "wave_height": Metric("Wave height", _WAVE_HEIGHT),
}


def _humanize(variable: str) -> str:
    return variable.replace("_", " ").capitalize()


def render_reading(variable: str, value: float | None) -> str:
    """Render one reading as ``name value unit (band)``, banding when known.

    Args:
        variable: The open-meteo variable name (for example ``"pm2_5"``).
        value: The raw reading, or ``None`` when the API supplied no value.

    Returns:
        A self-describing fragment: a banded reading for a known metric (for
        example ``"PM2.5 12.0 µg/m³ (fair)"``), or a plain ``name value`` for an
        unbanded variable, or ``name n/a`` when the value is missing.
    """
    metric = _METRICS.get(variable)
    name = metric.name if metric is not None else _humanize(variable)
    if value is None:
        return f"{name} n/a"
    if metric is None:
        return f"{name} {value:.1f}"
    unit = f" {metric.scale.unit}" if metric.scale.unit else ""
    return f"{name} {value:.1f}{unit} ({classify(metric.scale, value)})"
