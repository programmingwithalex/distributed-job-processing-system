import logging
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4


correlation_identifier_context: ContextVar[str] = ContextVar(
    "correlation_identifier",
    default="unset",
)


class CorrelationIdentifierFilter(logging.Filter):
    """Inject the current correlation identifier into log records."""

    def filter(self, log_record: logging.LogRecord) -> bool:
        """Populate the correlation identifier field for a log record.

        Args:
            log_record: Log record that will be emitted by the logger

        Returns:
            True so the log record continues through the pipeline
        """
        log_record.correlation_identifier = correlation_identifier_context.get()
        return True


def configure_application_logging() -> None:
    """Configure application logging with correlation identifier support."""
    root_logger = logging.getLogger()

    if any(isinstance(logging_filter, CorrelationIdentifierFilter) for logging_filter in root_logger.filters):
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] [correlation_id=%(correlation_identifier)s] %(message)s",
    )
    root_logger.addFilter(CorrelationIdentifierFilter())


def generate_correlation_identifier() -> str:
    """Generate a new correlation identifier for a request or task."""
    return str(uuid4())


@contextmanager
def correlation_identifier_context_scope(correlation_identifier: str):
    """Set the current correlation identifier for the duration of a scoped operation.

    Args:
        correlation_identifier: Correlation identifier to expose in logs while the scope is active
    """
    correlation_identifier_token = correlation_identifier_context.set(correlation_identifier)
    try:
        yield
    finally:
        correlation_identifier_context.reset(correlation_identifier_token)