from datetime import datetime, timedelta, timezone
import asyncio

from fastapi.testclient import TestClient

from alerts.gmail import GmailStoppedAlert
from alerts.switch import EmailAlertSwitch
from app.config import Settings
from app.main import app
from app.models import ServiceObservation
from app.monitoring.monitor import ServiceMonitor

SECRET = "super-secret-app-password"


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


class FakeDatabase:
    """Mocks only the MSSQL boundary; rows are keyed by service so mapping errors are visible."""
    def __init__(self, rows=None, available=True):
        self.rows, self.available = rows or {}, available
        self.settings = Settings(_env_file=None)
        self.warning = None if available else "MSSQL unavailable: OperationalError. Retrying automatically."
    def check(self): return self.available
    def record(self, observations): pass
    def last_known_statuses(self): return {}
    def history(self, service_name, hours): return list(self.rows.get(service_name, [])) if self.available else None


def install_fake_monitor(tmp_path, database, states=("RUNNING",)):
    names = ["KepwareServerV7", "KepwareServerLoggerV7"]
    sequence = iter([[ServiceObservation(service_name=n, display_name=n, status=s, startup_type="Auto", last_checked=datetime.now(timezone.utc)) for n in names] for s in states])
    settings = Settings(_env_file=None, smtp_host="smtp.gmail.com", smtp_username="sender@example.com", smtp_password=SECRET, alert_from="sender@example.com", alert_to="recipient@example.com")
    monitor = ServiceMonitor(database, 15, GmailStoppedAlert(settings, switch=EmailAlertSwitch(True, tmp_path / "switch.json")), discoverer=lambda: next(sequence))
    async def run():
        for _ in states: await monitor.collect()
    asyncio.run(run())
    app.state.monitor = monitor
    return monitor


def local_client():
    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_email_kill_switch_toggle_keeps_monitoring(tmp_path):
    monitor = install_fake_monitor(tmp_path, FakeDatabase())
    client = local_client()
    assert client.get("/api/services").json()["email_alerts"]["enabled"] is True
    off = client.put("/api/alerts/email", json={"enabled": False}, headers={"Origin": "http://127.0.0.1:8000"})
    assert off.status_code == 200 and off.json()["enabled"] is False
    services = client.get("/api/services").json()
    assert services["email_alerts"]["enabled"] is False and services["counts"]["total"] == 2
    assert EmailAlertSwitch(True, tmp_path / "switch.json").enabled is False
    assert client.put("/api/alerts/email", json={"enabled": True}).json()["enabled"] is True
    assert monitor.error is None


def test_email_kill_switch_rejects_cross_site_and_non_json(tmp_path):
    install_fake_monitor(tmp_path, FakeDatabase())
    client = local_client()
    assert client.put("/api/alerts/email", json={"enabled": False}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert TestClient(app, base_url="http://evil.example").put("/api/alerts/email", json={"enabled": False}).status_code == 403
    assert client.put("/api/alerts/email", content="enabled=false", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 422
    assert client.get("/api/alerts").json()["enabled"] is True


def test_responses_never_contain_smtp_secret(tmp_path):
    install_fake_monitor(tmp_path, FakeDatabase())
    client = local_client()
    for path in ("/api/services", "/api/health", "/api/alerts", "/"):
        body = client.get(path).text
        assert SECRET not in body and "recipient@example.com" not in body


def test_history_is_for_the_requested_service_only(tmp_path):
    now = datetime.now(timezone.utc)
    rows = {"KepwareServerV7": [{"status": "STOPPED", "startup_type": "Auto", "checked_at": now.isoformat(), "hostname": "h"}],
            "KepwareServerLoggerV7": [{"status": "RUNNING", "startup_type": "Auto", "checked_at": now.isoformat(), "hostname": "h"}]}
    install_fake_monitor(tmp_path, FakeDatabase(rows))
    body = local_client().get("/api/services/KepwareServerV7/history?hours=24").json()
    assert body["service_name"] == "KepwareServerV7" and body["source"] == "database"
    assert [x["status"] for x in body["history"]] == ["STOPPED"]


def test_history_falls_back_to_in_memory_changes_when_mssql_unavailable(tmp_path):
    install_fake_monitor(tmp_path, FakeDatabase(available=False), states=("RUNNING", "RUNNING", "STOPPED", "RUNNING"))
    body = local_client().get("/api/services/KepwareServerLoggerV7/history?hours=1").json()
    assert body["source"] == "memory" and body["available"] is False and "MSSQL unavailable" in body["message"]
    assert [x["status"] for x in body["history"]] == ["RUNNING", "STOPPED", "RUNNING"]
    assert local_client().get("/api/services/NotAService/history?hours=1").json()["history"] == []


def test_in_memory_history_keeps_state_at_window_start(tmp_path):
    monitor = install_fake_monitor(tmp_path, FakeDatabase(available=False))
    monitor._recent["KepwareServerV7"][0]["checked_at"] -= timedelta(hours=3)
    history = monitor.recent_history("KepwareServerV7", 1)
    assert [x["status"] for x in history] == ["RUNNING"]
