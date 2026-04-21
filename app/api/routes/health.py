from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health_status() -> dict[str, str]:
    """Return a simple health status payload for the API service."""
    return {"status": "ok"}
