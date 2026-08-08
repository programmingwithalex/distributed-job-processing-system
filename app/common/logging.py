import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4


correlation_identifier_context: ContextVar[str] = ContextVar(
    "correlation_identifier",
    default="unset",
)
is_correlation_identifier_log_record_factory_configured = False


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
    Wrap a log record factory so every record has a correlation identifier.

    Args:
        existing_log_record_factory: Existing logging factory that creates log records

    Returns:
        Wrapped factory that populates correlation_identifier when missing
    """

    def correlation_identifier_log_record_factory(*args, **kwargs) -> logging.LogRecord:
        """
        Create a log record enriched with the current correlation identifier.

        Args:
            *args: Positional arguments forwarded to the standard record factory
            **kwargs: Keyword arguments forwarded to the standard record factory

        Returns:
            Log record with correlation_identifier populated for formatter safety
        """
        log_record = existing_log_record_factory(*args, **kwargs)

        if not hasattr(log_record, "correlation_identifier"):
            log_record.correlation_identifier = correlation_identifier_context.get()

        return log_record

    return correlation_identifier_log_record_factory


def configure_application_logging() -> None:
    """Configure application logging with correlation identifier support."""
    global is_correlation_identifier_log_record_factory_configured

    root_logger = logging.getLogger()

    if not is_correlation_identifier_log_record_factory_configured:
        logging.setLogRecordFactory(
            build_correlation_identifier_log_record_factory(logging.getLogRecordFactory())
        )
        is_correlation_identifier_log_record_factory_configured = True

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] [correlation_id=%(correlation_identifier)s] %(message)s",
    )

    for root_handler in root_logger.handlers:
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