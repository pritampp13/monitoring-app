from datetime import datetime, timezone
import asyncio

from alerts.gmail import GmailStoppedAlert
from app.config import Settings
from app.models import ServiceObservation
from app.monitoring.monitor import ServiceMonitor


def observation(status: str) -> ServiceObservation:
    return ServiceObservation(service_name="KepwareServerV7", display_name="Kepware Server Runtime", status=status, startup_type="Auto", last_checked=datetime.now(timezone.utc))


class FakeDatabase:
    def __init__(self): self.recorded = []
    def last_known_statuses(self): return {}
    def record(self, observations): self.recorded.append(observations)


class FakeAlerts:
    def __init__(self): self.calls = []; self.warning = None
    def send(self, service, previous): self.calls.append((service.status, previous)); return True


def test_only_running_to_stopped_transition_sends_once():
    sequence = iter([[observation("RUNNING")], [observation("STOPPED")], [observation("STOPPED")], [observation("RUNNING")], [observation("STOPPED")]])
    alerts, database = FakeAlerts(), FakeDatabase()
    monitor = ServiceMonitor(database, 15, alerts, discoverer=lambda: next(sequence))
    async def run():
        for _ in range(5): await monitor.collect()
    asyncio.run(run())
    assert alerts.calls == [("STOPPED", "RUNNING"), ("STOPPED", "RUNNING")]


def test_smtp_failure_is_safe_and_does_not_expose_password():
    def broken(*args, **kwargs): raise OSError("network unavailable")
    settings = Settings(smtp_host="smtp.gmail.com", smtp_username="sender@example.com", smtp_password="super-secret", alert_from="sender@example.com", alert_to="recipient@example.com")
    alert = GmailStoppedAlert(settings, smtp_factory=broken)
    assert not alert.send(observation("STOPPED"), "RUNNING")
    assert "super-secret" not in alert.warning


def test_gmail_message_uses_starttls_and_required_subject():
    captured = {}
    class FakeSmtp:
        def __init__(self, *args, **kwargs): captured["connection"] = args
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def ehlo(self): captured["ehlo"] = captured.get("ehlo", 0) + 1
        def starttls(self, **kwargs): captured["tls"] = True
        def login(self, username, password): captured["login"] = (username, password)
        def send_message(self, message): captured["message"] = message
    settings = Settings(smtp_host="smtp.gmail.com", smtp_username="sender@example.com", smtp_password="app-password", alert_from="sender@example.com", alert_to="recipient@example.com")
    assert GmailStoppedAlert(settings, FakeSmtp).send(observation("STOPPED"), "RUNNING")
    assert captured["tls"] and captured["ehlo"] == 2
    assert captured["message"]["Subject"].startswith("[ALERT] Service STOPPED - KepwareServerV7 on ")
    assert "changed from RUNNING to STOPPED" in captured["message"].get_content()
