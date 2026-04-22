from uuid import uuid4

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.common.logging import (
    configure_application_logging,
    correlation_identifier_context_scope,
)


class CorrelationIdentifierMiddleware(BaseHTTPMiddleware):
    """Attach a correlation identifier to each API request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process a request while exposing a stable correlation identifier.

        Args:
            request: Incoming Starlette request object
            call_next: Downstream request handler callable

        Returns:
            HTTP response enriched with the correlation identifier header
        """
        correlation_identifier = request.headers.get("X-Request-ID", str(uuid4()))

        with correlation_identifier_context_scope(correlation_identifier=correlation_identifier):
            response = await call_next(request)

        response.headers["X-Request-ID"] = correlation_identifier
        return response


def create_api_application() -> FastAPI:
    """Create and configure the FastAPI application for the API service."""
    configure_application_logging()
    api_application = FastAPI(title="distributed-job-processing-system")
    api_application.add_middleware(CorrelationIdentifierMiddleware)
    api_application.include_router(health_router)
    api_application.include_router(jobs_router)
    return api_application


app = create_api_application()
