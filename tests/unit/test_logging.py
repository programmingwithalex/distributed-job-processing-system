import io
import logging

from fastapi.testclient import TestClient

from app.api.main import app
from app.common.logging import (
    configure_application_logging,
    correlation_identifier_context_scope,
)


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