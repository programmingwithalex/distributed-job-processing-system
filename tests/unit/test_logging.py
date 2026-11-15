"""
Verify request correlation and structured application logging without external services.
Check that JSON records preserve message and exception content without extra physical lines.
Use the OpenTelemetry API to verify span context is captured before its scope ends.
These tests do not create exported traces or require Alloy, Loki, Tempo, or Grafana.
"""

import io
import json
import logging
import sys

from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, use_span

from app.api.main import app
from app.common.logging import (
    StructuredJSONFormatter,
    configure_application_logging,
    correlation_identifier_context_scope,
)
from app.worker.celery_app import celery_app


def test_api_returns_generated_correlation_identifier_header() -> None:
    """Verify the API adds a correlation identifier header when one is not supplied."""
    api_test_client = TestClient(app)

    response = api_test_client.get("/health")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


def test_api_preserves_supplied_correlation_identifier_header() -> None:
    """Verify the API reuses the caller-provided correlation identifier."""
    api_test_client = TestClient(app)

    response = api_test_client.get("/health", headers={"X-Request-ID": "integration-test-request"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "integration-test-request"


def test_child_logger_formats_correlation_identifier_without_logging_errors() -> None:
    """Verify child loggers can format correlation identifiers safely."""
    configure_application_logging()
    log_output_stream = io.StringIO()
    child_logger = logging.getLogger("app.tests.logging.child")
    child_logger_handler = logging.StreamHandler(log_output_stream)
    child_logger_handler.setFormatter(
        logging.Formatter("%(correlation_identifier)s %(message)s")
    )
    child_logger.addHandler(child_logger_handler)
    child_logger.setLevel(logging.INFO)
    child_logger.propagate = False

    try:
        with correlation_identifier_context_scope("integration-test-request"):
            child_logger.info("child logger emitted")
    finally:
        child_logger.removeHandler(child_logger_handler)
        child_logger_handler.close()

    assert "integration-test-request child logger emitted" in log_output_stream.getvalue()


def test_application_logging_configures_json_root_handlers() -> None:
    """Verify application handlers emit JSON and Celery preserves those handlers."""
    configure_application_logging()

    root_handlers = logging.getLogger().handlers

    assert root_handlers
    assert all(
        isinstance(root_handler.formatter, StructuredJSONFormatter)
        for root_handler in root_handlers
    )
    assert celery_app.conf.worker_hijack_root_logger is False


def test_json_logs_preserve_request_context_and_escape_multiline_messages() -> None:
    """Verify log metadata and message escaping without fabricating trace identifiers."""
    configure_application_logging()
    formatter = StructuredJSONFormatter(service_name="api", environment="test")
    with correlation_identifier_context_scope("structured-request"):
        log_record = logging.makeLogRecord(
            {
                "name": "app.tests.logging.json",
                "levelname": "INFO",
                "msg": 'first "line"\nsecond line',
            }
        )

    formatted_record = formatter.format(log_record)
    log_payload = json.loads(formatted_record)

    assert len(formatted_record.splitlines()) == 1
    assert log_payload["service_name"] == "api"
    assert log_payload["environment"] == "test"
    assert log_payload["level"] == "INFO"
    assert log_payload["logger"] == "app.tests.logging.json"
    assert log_payload["correlation_id"] == "structured-request"
    assert log_payload["message"] == 'first "line"\nsecond line'
    assert log_payload["trace_id"] is None
    assert log_payload["span_id"] is None


def test_json_logs_capture_trace_context_before_the_span_scope_ends() -> None:
    """Verify captured trace IDs survive scope exit and do not leak into later records."""
    configure_application_logging()
    formatter = StructuredJSONFormatter(service_name="api", environment="test")
    span_context = SpanContext(trace_id=1, span_id=2, is_remote=False)
    with use_span(NonRecordingSpan(span_context)):
        traced_record = logging.makeLogRecord({"msg": "inside span"})

    traced_payload = json.loads(formatter.format(traced_record))
    untraced_record = logging.makeLogRecord({"msg": "outside span"})
    untraced_payload = json.loads(formatter.format(untraced_record))

    assert traced_payload["trace_id"] == "00000000000000000000000000000001"
    assert traced_payload["span_id"] == "0000000000000002"
    assert untraced_payload["trace_id"] is None
    assert untraced_payload["span_id"] is None


def test_json_logs_keep_exception_tracebacks_in_one_record() -> None:
    """Verify a traceback remains queryable inside one JSON log record."""
    formatter = StructuredJSONFormatter(service_name="api", environment="test")
    try:
        raise ValueError("controlled logging failure")
    except ValueError:
        log_record = logging.makeLogRecord(
            {"msg": "operation failed", "exc_info": sys.exc_info()}
        )

    formatted_record = formatter.format(log_record)
    log_payload = json.loads(formatted_record)

    assert len(formatted_record.splitlines()) == 1
    assert log_payload["message"] == "operation failed"
    assert "Traceback" in log_payload["exception"]
    assert "ValueError: controlled logging failure" in log_payload["exception"]