from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.common.logging import (
    configure_application_logging,
    correlation_identifier_context_scope,
)

API_HTTP_REQUESTS = Counter(
    "api_http_requests",
    "Total HTTP requests handled by the API",
    ["method", "route", "status_code"],
)
API_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "api_http_request_duration_seconds",
    "API HTTP request duration in seconds",
    ["method", "route", "status_code"],
)


def get_metric_path_label(request: Request) -> str:
    """Return a bounded path label from the resolved request route.

    Args:
        request: Incoming Starlette request

    Returns:
        Stable route template or unmatched fallback label
    """
    route_path = getattr(request.scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else "unmatched"


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Record bounded request metrics for application endpoints."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process a request and publish its response metrics.

        Args:
            request: Incoming Starlette request
            call_next: Downstream request handler callable

        Returns:
            HTTP response from the downstream handler
        """
        if request.url.path == "/metrics":
            return await call_next(request)

        started_at = perf_counter()
        response = await call_next(request)
        metric_labels = {
            "method": request.method,
            "route": get_metric_path_label(request),
            "status_code": str(response.status_code),
        }
        API_HTTP_REQUESTS.labels(**metric_labels).inc()
        API_HTTP_REQUEST_DURATION_SECONDS.labels(**metric_labels).observe(perf_counter() - started_at)
        return response


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
    api_application.add_middleware(PrometheusMetricsMiddleware)
    api_application.mount("/metrics", make_asgi_app())
    api_application.include_router(health_router)
    api_application.include_router(jobs_router)
    return api_application


app = create_api_application()
