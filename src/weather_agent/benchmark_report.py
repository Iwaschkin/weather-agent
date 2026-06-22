"""Persist, load, and render :class:`~weather_agent.benchmark.BenchmarkReport`.

The serialised shape is plain JSON (typed via ``TypedDict``), and deserialisation
validates every field into the typed model rather than trusting the payload, so a
hand-edited or stale report fails loudly instead of producing a malformed result.
File I/O is the only side effect; serialisation and markdown rendering are pure.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, TypedDict, cast

from weather_agent.benchmark import BenchmarkReport, RunStat
from weather_agent.observability import ToolCall

if TYPE_CHECKING:
    from pathlib import Path


class _ToolCallDict(TypedDict):
    """Serialised form of a :class:`~weather_agent.observability.ToolCall`."""

    name: str
    duration_ms: float
    succeeded: bool


class _RunStatDict(TypedDict):
    """Serialised form of a :class:`~weather_agent.benchmark.RunStat`."""

    query: str
    tool_calls: list[_ToolCallDict]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model_latency_ms: int


class _ReportDict(TypedDict):
    """Serialised form of a :class:`~weather_agent.benchmark.BenchmarkReport`."""

    model_id: str
    host: str
    captured_at: str
    runs: list[_RunStatDict]


class BenchmarkReportError(ValueError):
    """Raised when a serialised benchmark report is missing or malformed."""


def report_to_dict(report: BenchmarkReport) -> _ReportDict:
    """Convert a report into its JSON-serialisable dictionary form."""
    return {
        "model_id": report.model_id,
        "host": report.host,
        "captured_at": report.captured_at.isoformat(),
        "runs": [_run_to_dict(run) for run in report.runs],
    }


def _run_to_dict(run: RunStat) -> _RunStatDict:
    return {
        "query": run.query,
        "tool_calls": [_tool_to_dict(call) for call in run.tool_calls],
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "model_latency_ms": run.model_latency_ms,
    }


def _tool_to_dict(call: ToolCall) -> _ToolCallDict:
    return {"name": call.name, "duration_ms": call.duration_ms, "succeeded": call.succeeded}


def report_to_json(report: BenchmarkReport) -> str:
    """Serialise a report to an indented JSON string."""
    return json.dumps(report_to_dict(report), indent=2)


def report_from_json(text: str) -> BenchmarkReport:
    """Parse a report from a JSON string, validating its structure.

    Args:
        text: The JSON document to parse.

    Returns:
        The validated report.

    Raises:
        BenchmarkReportError: If the text is not valid JSON or any field is
            missing or of the wrong type.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        detail = "report is not valid JSON"
        raise BenchmarkReportError(detail) from error
    return report_from_dict(data)


def report_from_dict(data: object) -> BenchmarkReport:
    """Validate an untyped payload into a :class:`BenchmarkReport`.

    Args:
        data: The parsed JSON object.

    Returns:
        The validated report.

    Raises:
        BenchmarkReportError: If a field is missing or of the wrong type.
    """
    obj = _as_dict(data, "report")
    return BenchmarkReport(
        model_id=_str_field(obj, "model_id"),
        host=_str_field(obj, "host"),
        captured_at=_datetime_field(obj, "captured_at"),
        runs=tuple(_run_from_dict(item) for item in _list_field(obj, "runs")),
    )


def _run_from_dict(data: object) -> RunStat:
    obj = _as_dict(data, "run")
    return RunStat(
        query=_str_field(obj, "query"),
        tool_calls=tuple(_tool_from_dict(item) for item in _list_field(obj, "tool_calls")),
        input_tokens=_int_field(obj, "input_tokens"),
        output_tokens=_int_field(obj, "output_tokens"),
        total_tokens=_int_field(obj, "total_tokens"),
        model_latency_ms=_int_field(obj, "model_latency_ms"),
    )


def _tool_from_dict(data: object) -> ToolCall:
    obj = _as_dict(data, "tool call")
    return ToolCall(
        name=_str_field(obj, "name"),
        duration_ms=_float_field(obj, "duration_ms"),
        succeeded=_bool_field(obj, "succeeded"),
    )


def write_report(report: BenchmarkReport, directory: Path) -> Path:
    """Write a report as JSON into ``directory`` and return the file path.

    The filename is the capture timestamp and model id, so successive runs do not
    overwrite each other. The directory is created if it does not exist.

    Args:
        report: The report to persist.
        directory: The directory to write into.

    Returns:
        The path of the written file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.captured_at.strftime("%Y%m%dT%H%M%S")
    safe_model = report.model_id.replace(":", "-").replace("/", "-")
    path = directory / f"{stamp}-{safe_model}.json"
    _ = path.write_text(report_to_json(report), encoding="utf-8")
    return path


def load_report(path: Path) -> BenchmarkReport:
    """Load and validate a report from a JSON file.

    Args:
        path: The report file to read.

    Returns:
        The validated report.

    Raises:
        OSError: If the file cannot be read.
        BenchmarkReportError: If its contents are not a valid report.
    """
    return report_from_json(path.read_text(encoding="utf-8"))


def format_report_markdown(report: BenchmarkReport) -> str:
    """Render a report as a markdown table for a README or report document.

    Args:
        report: The report to render.

    Returns:
        A markdown document with the headline cost, latency, and routing figures.
    """
    summary = report.summary
    lines = [
        f"## Benchmark: {report.model_id}",
        "",
        f"_{summary.runs} queries, captured {report.captured_at.isoformat()}_",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total tokens | {summary.total_tokens} |",
        f"| Mean tokens/run | {summary.mean_total_tokens:.0f} |",
        f"| Mean latency | {summary.mean_latency_ms:.0f} ms |",
        f"| p50 / p95 latency | {summary.p50_latency_ms:.0f} / {summary.p95_latency_ms:.0f} ms |",
        f"| Tool calls | {summary.total_tool_calls} ({summary.failed_tool_calls} failed) |",
    ]
    if summary.tool_counts:
        breakdown = ", ".join(f"`{name}` x{count}" for name, count in summary.tool_counts)
        lines.extend(["", f"Tool breakdown: {breakdown}"])
    return "\n".join(lines)


def _as_dict(data: object, context: str) -> dict[str, object]:
    if not isinstance(data, dict):
        detail = f"{context} must be an object"
        raise BenchmarkReportError(detail)
    return cast("dict[str, object]", data)


def _str_field(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        detail = f"field {key!r} must be a string"
        raise BenchmarkReportError(detail)
    return value


def _int_field(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        detail = f"field {key!r} must be an integer"
        raise BenchmarkReportError(detail)
    return value


def _float_field(data: dict[str, object], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        detail = f"field {key!r} must be a number"
        raise BenchmarkReportError(detail)
    return float(value)


def _bool_field(data: dict[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        detail = f"field {key!r} must be a boolean"
        raise BenchmarkReportError(detail)
    return value


def _list_field(data: dict[str, object], key: str) -> list[object]:
    value = data.get(key)
    if not isinstance(value, list):
        detail = f"field {key!r} must be a list"
        raise BenchmarkReportError(detail)
    return cast("list[object]", value)


def _datetime_field(data: dict[str, object], key: str) -> datetime:
    text = _str_field(data, key)
    try:
        return datetime.fromisoformat(text)
    except ValueError as error:
        detail = f"field {key!r} must be an ISO timestamp"
        raise BenchmarkReportError(detail) from error
