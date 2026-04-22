import logging

from fastapi import APIRouter

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def get_health_status() -> dict[str, str]:
    """Return a simple health status payload for the API service."""
    logger.info("Handled API health check request")
    return {"status": "ok"}
