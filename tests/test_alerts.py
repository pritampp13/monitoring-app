from datetime import datetime, timezone
import asyncio
import logging
import smtplib

import pytest

from alerts.gmail import GmailStoppedAlert
from alerts.switch import EmailAlertSwitch
from app.config import Settings
from app.models import ServiceObservation
from app.monitoring.monitor import ServiceMonitor

SECRET = "super-secret-app-password"


def observation(status: str, name: str = "KepwareServerV7") -> ServiceObservation:
    return ServiceObservation(service_name=name, display_name="Kepware Server Runtime", status=status, startup_type="Auto", last_checked=datetime.now(timezone.utc))


def smtp_settings(**overrides) -> Settings:
    values = dict(_env_file=None, smtp_host="smtp.gmail.com", smtp_port=587, smtp_username="sender@example.com", smtp_password=SECRET,
                  alert_from="sender@example.com", alert_to="recipient@example.com")
    values.update(overrides)
    return Settings(**values)


class FakeDatabase:
    def __init__(self, restored=None): self.recorded = []; self.restored = restored or {}
    def last_known_statuses(self): return dict(self.restored)
    def record(self, observations): self.recorded.append(observations)


class FakeAlerts:
    def __init__(self): self.calls = []; self.warning = None
    def send(self, service, previous): self.calls.append((service.service_name, service.status, previous)); return True


class FakeSmtp:
    sent = []
    def __init__(self, *args, **kwargs): self.ehlos = 0; self.tls = False
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def ehlo(self): self.ehlos += 1
    def starttls(self, **kwargs): self.tls = True
    def login(self, username, password): pass
    def send_message(self, message): FakeSmtp.sent.append((message, self.tls, self.ehlos))


def run_states(states, alerts, database=None, restore=False):
    """Feed real-shaped observations through the monitor exactly as the polling loop does."""
    sequence = iter([[observation(s)] for s in states])
    database = database or FakeDatabase()
    monitor = ServiceMonitor(database, 15, alerts, discoverer=lambda: next(sequence))
    async def run():
        if restore: await monitor._restore_previous_states()
        for _ in states: await monitor.collect()
        await monitor.wait_for_alerts()
    asyncio.run(run())
    return monitor, database


def test_only_running_to_stopped_transition_sends_once():
    alerts = FakeAlerts()
    run_states(["RUNNING", "STOPPED", "STOPPED", "RUNNING", "STOPPED"], alerts)
    assert [c[1:] for c in alerts.calls] == [("STOPPED", "RUNNING"), ("STOPPED", "RUNNING")]


def test_continuously_stopped_service_alerts_only_once():
    alerts = FakeAlerts()
    run_states(["RUNNING"] + ["STOPPED"] * 40, alerts)
    assert len(alerts.calls) == 1


def test_initial_discovery_of_stopped_service_does_not_alert():
    alerts = FakeAlerts()
    run_states(["STOPPED", "STOPPED"], alerts)
    assert alerts.calls == []


def test_stop_through_stop_pending_still_alerts_once():
    alerts = FakeAlerts()
    run_states(["RUNNING", "STOP_PENDING", "STOPPED", "STOPPED"], alerts)
    assert [c[1:] for c in alerts.calls] == [("STOPPED", "RUNNING")]


def test_failed_start_does_not_alert():
    alerts = FakeAlerts()
    run_states(["STOPPED", "START_PENDING", "STOPPED"], alerts)
    assert alerts.calls == []


def test_restored_running_state_alerts_on_first_stopped_observation():
    alerts = FakeAlerts()
    run_states(["STOPPED", "STOPPED"], alerts, FakeDatabase({"KepwareServerV7": "RUNNING"}), restore=True)
    assert len(alerts.calls) == 1


def test_gmail_message_uses_starttls_and_required_content(tmp_path):
    FakeSmtp.sent = []
    alert = GmailStoppedAlert(smtp_settings(), FakeSmtp, EmailAlertSwitch(True, tmp_path / "switch.json"))
    assert alert.send(observation("STOPPED", "RobexLicenseServer1x64"), "RUNNING")
    message, tls, ehlos = FakeSmtp.sent[0]
    assert tls and ehlos == 2
    assert message["Subject"] == "KepwareEX Service Stopped - RobexLicenseServer1x64"
    assert message["To"] == "recipient@example.com"
    body = message.get_content()
    assert "Service Name: RobexLicenseServer1x64" in body and "Status: STOPPED" in body
    stopped_at = next(line for line in body.splitlines() if line.startswith("Stopped At: "))
    datetime.strptime(stopped_at[len("Stopped At: "):][:20], "%d-%b-%Y %H:%M:%S")
    assert SECRET not in body


def test_kill_switch_off_blocks_email_but_not_monitoring(tmp_path):
    FakeSmtp.sent = []
    alert = GmailStoppedAlert(smtp_settings(), FakeSmtp, EmailAlertSwitch(False, tmp_path / "switch.json"))
    monitor, database = run_states(["RUNNING", "STOPPED", "STOPPED"], alert)
    assert FakeSmtp.sent == [] and alert.suppressed_count == 1
    assert monitor.error is None and len(database.recorded) == 3
    assert monitor.services[0].status == "STOPPED" and alert.warning is None


def test_kill_switch_on_restores_email(tmp_path):
    FakeSmtp.sent = []
    switch = EmailAlertSwitch(False, tmp_path / "switch.json")
    alert = GmailStoppedAlert(smtp_settings(), FakeSmtp, switch)
    assert not alert.send(observation("STOPPED"), "RUNNING")
    switch.set(True)
    assert alert.send(observation("STOPPED"), "RUNNING") and len(FakeSmtp.sent) == 1


def test_kill_switch_persists_and_survives_corrupt_file(tmp_path):
    path = tmp_path / "data" / "switch.json"
    EmailAlertSwitch(True, path).set(False)
    assert EmailAlertSwitch(True, path).enabled is False
    path.write_text("{not json", encoding="utf-8")
    corrupt = EmailAlertSwitch(True, path)
    assert corrupt.enabled is True and "unreadable" in corrupt.warning


@pytest.mark.parametrize("error, expected", [
    (OSError("network unavailable"), "connection failed"),
    (TimeoutError("timed out"), "timed out"),
    (smtplib.SMTPAuthenticationError(535, b"bad credentials " + SECRET.encode()), "authentication rejected"),
    (smtplib.SMTPRecipientsRefused({"recipient@example.com": (550, b"no such user")}), "recipient refused"),
])
def test_smtp_failures_are_safe_and_do_not_expose_password(tmp_path, caplog, error, expected):
    def broken(*args, **kwargs): raise error
    alert = GmailStoppedAlert(smtp_settings(), broken, EmailAlertSwitch(True, tmp_path / "switch.json"))
    with caplog.at_level(logging.INFO):
        assert not alert.send(observation("STOPPED"), "RUNNING")
    assert expected in alert.warning
    assert SECRET not in alert.warning and SECRET not in caplog.text and SECRET not in str(alert.status())


def test_smtp_failure_does_not_stop_monitoring(tmp_path):
    def broken(*args, **kwargs): raise OSError("network unavailable")
    alert = GmailStoppedAlert(smtp_settings(), broken, EmailAlertSwitch(True, tmp_path / "switch.json"))
    monitor, database = run_states(["RUNNING", "STOPPED", "RUNNING"], alert)
    assert monitor.error is None and len(database.recorded) == 3 and monitor.services[0].status == "RUNNING"


def test_unexpected_alert_exception_does_not_mark_monitor_failed():
    class Exploding:
        warning = None
        def send(self, *args): raise RuntimeError("boom")
    monitor, database = run_states(["RUNNING", "STOPPED"], Exploding())
    assert monitor.error is None and len(database.recorded) == 2


def test_missing_smtp_settings_named_without_values(tmp_path):
    settings = smtp_settings(smtp_username="", alert_to="<recipient-address@example.com>")
    alert = GmailStoppedAlert(settings, FakeSmtp, EmailAlertSwitch(True, tmp_path / "switch.json"))
    assert not settings.smtp_configured
    assert not alert.send(observation("STOPPED"), "RUNNING")
    assert "SMTP_USERNAME" in alert.warning and "ALERT_TO" in alert.warning and SECRET not in alert.warning


def test_placeholder_password_is_not_configured():
    assert "SMTP_PASSWORD" in smtp_settings(smtp_password="<MY_GMAIL_APP_PASSWORD>").smtp_missing


def test_alert_recipient_alias_and_env_names(monkeypatch):
    for name, value in {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": SECRET,
                        "ALERT_FROM": "sender@example.com", "ALERT_RECIPIENT": "recipient@example.com", "EMAIL_ALERTS_ENABLED": "false"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ALERT_TO", raising=False)
    settings = Settings(_env_file=None)
    assert settings.alert_to == "recipient@example.com" and settings.smtp_port == 587
    assert settings.smtp_configured and settings.email_alerts_enabled is False
