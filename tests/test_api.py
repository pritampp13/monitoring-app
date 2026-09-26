from fastapi.testclient import TestClient
from app.main import app


def test_health_and_services_are_live_shapes():
    with TestClient(app) as client:
        health = client.get("/api/health")
        services = client.get("/api/services")
    assert health.status_code == 200
    assert "database" in health.json()
    assert services.status_code == 200
    assert "services" in services.json() and "counts" in services.json()


def test_history_rejects_invalid_range():
    with TestClient(app) as client:
        response = client.get("/api/services/does-not-exist/history?hours=2")
    assert response.status_code == 400
