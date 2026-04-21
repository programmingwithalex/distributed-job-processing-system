from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router


def create_api_application() -> FastAPI:
    """Create and configure the FastAPI application for the API service."""
    api_application = FastAPI(title="distributed-job-processing-system")
    api_application.include_router(health_router)
    api_application.include_router(jobs_router)
    return api_application


app = create_api_application()
