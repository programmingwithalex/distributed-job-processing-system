import re

from fastapi.testclient import TestClient

from app.api.main import app


def test_metrics_endpoint_reports_api_request_metrics() -> None:
    """Verify normal API traffic is exported with bounded labels."""
    api_test_client = TestClient(app)

    health_response = api_test_client.get("/health")
    metrics_response = api_test_client.get("/metrics")

    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert "text/plain" in metrics_response.headers["content-type"]
    assert re.search(
        r'^api_http_requests_total\{method="GET",route="/health",status_code="200"\} [1-9][0-9.]*$',
        metrics_response.text,
        flags=re.MULTILINE,
    )
    assert re.search(
        r'^api_http_request_duration_seconds_count\{method="GET",route="/health",status_code="200"\} [1-9][0-9.]*$',
        metrics_response.text,
        flags=re.MULTILINE,
    )
    assert 'route="/metrics"' not in metrics_response.text