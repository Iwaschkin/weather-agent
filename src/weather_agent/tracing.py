"""Opt-in OpenTelemetry console tracing for the agent.

Strands instruments the agent's event loop, model calls, and tool calls with
OpenTelemetry spans. Enabling a console exporter prints those spans, which makes
one run's full execution tree (cycles, model calls, tool calls) visible for a
local demonstrator. Setting the global tracer provider is a process-wide side
effect, so this is opt-in and must be called once at startup, before the agent is
built.
"""

import logging

from strands.telemetry import StrandsTelemetry

logger = logging.getLogger(__name__)


def enable_console_tracing() -> None:
    """Enable OpenTelemetry span export to the console for this process.

    Installs a global tracer provider with a console span exporter. Call once at
    startup, before constructing the agent. No collector is required; spans are
    written to the console. Subsequent agent runs then emit their execution tree
    as spans.
    """
    _ = StrandsTelemetry().setup_console_exporter()
    logger.info("OpenTelemetry console tracing enabled")
