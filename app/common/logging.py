"""
Configure single-line JSON application logs with request and trace correlation fields.
Capture the request identifier and active OpenTelemetry span identifiers when each
record is created, so later formatting does not depend on the originating context.
Exceptions and stack traces remain inside one JSON record rather than separate log lines.
This module formats standard Python logs only; instrumentation creates spans and Alloy
will collect the output for delivery to Loki in a separate implementation step.

| Field            | Purpose                                           |
| ---------------- | ------------------------------------------------- |
| `correlation_id` | Our application-defined identifier for grouping logs |
| `trace_id`       | Identifies an actual distributed trace stored in Tempo |
| `span_id`        | Identifies the specific operation within that trace |

A propagated correlation ID can group logs across services without OpenTelemetry.
It does not create spans with timings and parent-child relationships for a trace view.
The Tempo description assumes tracing and export are configured; a trace ID alone
does not guarantee the trace has been sampled, exported, or stored.

| Concept      | Meaning                                                     |
| ------------ | ----------------------------------------------------------- |
| HTML `<span>` | An inline element used to group or style page content       |
| Tracing span | A measured operation with timing, IDs, and a parent reference |

These concepts are unrelated; a tracing span measures an operation's time interval.
Spans can represent internal Python work, database queries, or HTTP requests, not
just API calls. Each instrumented operation creates its own span ID rather than
reusing the browser's span ID, while operations in the same trace share a trace ID.

Illustrative trace records, with simplified IDs and example elapsed times:

| Operation       | Trace ID | Span ID | Parent ID | Start-End |
| --------------- | -------- | ------- | --------- | --------- |
| Browser request | `T`      | `A`     | None      | 0-100 ms  |
| FastAPI request | `T`      | `B`     | `A`       | 5-85 ms   |
| Validation      | `T`      | `C`     | `B`       | 10-15 ms  |
| Database call   | `T`      | `D`     | `B`       | 20-80 ms  |

Tempo groups exported spans by trace ID and uses parent IDs to establish the tree;
Grafana displays their timestamps as a timeline. Validation and the database call
are siblings under the FastAPI request, not parents of each other; their timestamps
show their order. A validation span needs explicit instrumentation or a supporting
integration. This example is not currently collected telemetry, and this module
only copies IDs from existing spans into logs without creating or exporting spans.
"""

import json
import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry.trace import format_span_id, format_trace_id, get_current_span

from app.common.config import get_application_settings

# correlation_id groups request or task logs using our application-defined identifier
# request correlation and json formatting work without opentelemetry
correlation_identifier_context: ContextVar[str] = ContextVar(
    "correlation_identifier",
    default="unset",
)
is_correlation_identifier_log_record_factory_configured = False


class StructuredJSONFormatter(logging.Formatter):
    """Format application records as JSON without splitting exception tracebacks."""

    def __init__(self, service_name: str, environment: str) -> None:
        """
        Set the bounded service and environment fields shared by emitted records.

        Args:
            service_name: Application service name supplied by OTEL_SERVICE_NAME
            environment: Deployment environment supplied by APP_ENV
        """
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, log_record: logging.LogRecord) -> str:
        """
        Serialize one record with its captured request, trace, and exception context.

        Args:
            log_record: Standard Python logging record to serialize

        Returns:
            Single-line JSON with null trace identifiers when no valid span was active
        """
        log_payload = {
            "timestamp": datetime.fromtimestamp(log_record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": log_record.levelname,
            "logger": log_record.name,
            "service_name": self.service_name,
            "environment": self.environment,
            "correlation_id": getattr(log_record, "correlation_identifier", "unset"),
            "trace_id": getattr(log_record, "trace_id", None),
            "span_id": getattr(log_record, "span_id", None),
            "message": log_record.getMessage(),
        }
        if log_record.exc_info:
            log_payload["exception"] = self.formatException(log_record.exc_info)
        if log_record.stack_info:
            log_payload["stack_trace"] = self.formatStack(log_record.stack_info)
        return json.dumps(log_payload)


class CorrelationIdentifierFilter(logging.Filter):
    """Inject the current correlation identifier into log records."""

    def filter(self, log_record: logging.LogRecord) -> bool:
        """
        Populate the correlation identifier field for a log record.

        Args:
            log_record: Log record that will be emitted by the logger

        Returns:
            True so the log record continues through the pipeline
        """
        log_record.correlation_identifier = correlation_identifier_context.get()
        return True


def build_correlation_identifier_log_record_factory(
    existing_log_record_factory: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    """
    Wrap a log record factory to capture request and OpenTelemetry trace context.

    Args:
        existing_log_record_factory: Existing logging factory that creates log records

    Returns:
        Wrapped factory that populates request context and valid trace identifiers
    """

    def correlation_identifier_log_record_factory(*args, **kwargs) -> logging.LogRecord:
        """
        Capture correlation and trace identifiers before the emitting context ends.

        Args:
            *args: Positional arguments forwarded to the standard record factory
            **kwargs: Keyword arguments forwarded to the standard record factory

        Returns:
            Log record with request context and nullable hexadecimal trace identifiers
        """
        log_record = existing_log_record_factory(*args, **kwargs)

        if not hasattr(log_record, "correlation_identifier"):
            log_record.correlation_identifier = correlation_identifier_context.get()

        # trace_id identifies the distributed trace; span_id identifies one operation within it
        # copying these ids lets logs link to the matching tempo trace once tracing is enabled
        # no active span means null ids; these helpers do not create spans or export telemetry
        # an instrumented backend can continue a faro browser trace while creating its own span id
        # this logging module does not enable browser-to-api propagation or export traces
        span_context = get_current_span().get_span_context()
        log_record.trace_id = (
            format_trace_id(span_context.trace_id) if span_context.is_valid else None
        )
        log_record.span_id = (
            format_span_id(span_context.span_id) if span_context.is_valid else None
        )
        return log_record

    return correlation_identifier_log_record_factory


def configure_application_logging() -> None:
    """
    Configure root handlers for JSON logs while preserving correlation-aware child loggers.

    Read service identity from OTEL_SERVICE_NAME and deployment identity from APP_ENV.
    Capture active span IDs through the OpenTelemetry API without creating or exporting spans.
    """
    global is_correlation_identifier_log_record_factory_configured

    root_logger = logging.getLogger()

    if not is_correlation_identifier_log_record_factory_configured:
        logging.setLogRecordFactory(
            build_correlation_identifier_log_record_factory(logging.getLogRecordFactory())
        )
        is_correlation_identifier_log_record_factory_configured = True

    logging.basicConfig(level=logging.INFO)
    application_settings = get_application_settings()
    json_formatter = StructuredJSONFormatter(
        service_name=application_settings.otel_service_name,
        environment=application_settings.app_env,
    )

    for root_handler in root_logger.handlers:
        root_handler.setFormatter(json_formatter)
        if not any(
            isinstance(logging_filter, CorrelationIdentifierFilter)
            for logging_filter in root_handler.filters
        ):
            root_handler.addFilter(CorrelationIdentifierFilter())


def generate_correlation_identifier() -> str:
    """
    Generate a new correlation identifier for a request or task.

    Returns:
        New correlation identifier
    """
    return str(uuid4())


@contextmanager
def correlation_identifier_context_scope(correlation_identifier: str):
    """
    Set the current correlation identifier for the duration of a scoped operation.

    Args:
        correlation_identifier: Correlation identifier to expose in logs while the scope is active
    """
    correlation_identifier_token = correlation_identifier_context.set(correlation_identifier)
    try:
        yield
    finally:
        correlation_identifier_context.reset(correlation_identifier_token)