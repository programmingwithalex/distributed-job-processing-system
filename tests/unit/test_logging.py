from fastapi.testclient import TestClient

from app.api.main import app


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