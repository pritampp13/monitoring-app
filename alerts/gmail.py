"""Gmail STARTTLS STOPPED-transition alerts. Credentials are environment-only."""
from datetime import datetime, timezone
from email.message import EmailMessage
import logging
import smtplib
import socket
import ssl
from collections.abc import Callable

from alerts.switch import EmailAlertSwitch
from app.config import Settings
from app.models import ServiceObservation

logger = logging.getLogger(__name__)


def format_stopped_at(moment: datetime) -> str:
    """Server-local time, e.g. 03-Oct-2026 15:42:18 (UTC+05:30)."""
    local = moment.astimezone()
    offset = local.strftime("%z")
    return f"{local.strftime('%d-%b-%Y %H:%M:%S')} (UTC{offset[:3]}:{offset[3:]})" if offset else local.strftime("%d-%b-%Y %H:%M:%S")


class GmailStoppedAlert:
    def __init__(self, settings: Settings, smtp_factory: Callable = smtplib.SMTP, switch: EmailAlertSwitch | None = None):
        self.settings = settings
        self.smtp_factory = smtp_factory
        self.switch = switch or EmailAlertSwitch(settings.email_alerts_enabled)
        self.last_sent_at: datetime | None = None
        self.last_error: str | None = None
        self.suppressed_count = 0

    @property
    def enabled(self) -> bool:
        return self.switch.enabled

    @property
    def warning(self) -> str | None:
        """Dashboard-safe message; names missing variables but never their values."""
        if not self.enabled:
            return None
        if not self.settings.smtp_configured:
            return f"Email alerts are ON but SMTP is not configured (missing: {', '.join(self.settings.smtp_missing)}). Add them to .env."
        return self.last_error or self.switch.warning

    def status(self) -> dict:
        return {"enabled": self.enabled, "configured": self.settings.smtp_configured, "warning": self.warning,
                "last_sent_at": self.last_sent_at, "updated_at": self.switch.updated_at, "suppressed_count": self.suppressed_count}

    def build_message(self, service: ServiceObservation, previous_status: str) -> EmailMessage:
        hostname = socket.gethostname()
        stopped_at = format_stopped_at(service.last_checked)
        message = EmailMessage()
        message["From"] = self.settings.alert_from
        message["To"] = self.settings.alert_to
        message["Subject"] = f"KepwareEX Service Stopped - {service.service_name}"
        message.set_content(
            f"Service Name: {service.service_name}\n"
            f"Status: {service.status}\n"
            f"Stopped At: {stopped_at}\n\n"
            f"Display Name: {service.display_name}\n"
            f"Server: {hostname}\n"
            f"Previous Status: {previous_status}\n\n"
            "The KepwareEX service changed from RUNNING to STOPPED. 'Stopped At' is the time the monitor "
            "first observed the STOPPED state. Please investigate the service.\n"
        )
        return message

    def send(self, service: ServiceObservation, previous_status: str) -> bool:
        if not self.enabled:
            self.suppressed_count += 1
            logger.info("Email alerts are OFF; STOPPED alert for %s was not sent", service.service_name)
            return False
        if not self.settings.smtp_configured:
            logger.warning("STOPPED alert for %s not sent: SMTP not configured (missing %s)", service.service_name, ", ".join(self.settings.smtp_missing))
            return False
        message = self.build_message(service, previous_status)
        try:
            with self.smtp_factory(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(message)
            self.last_sent_at, self.last_error = datetime.now(timezone.utc), None
            logger.info("STOPPED alert email sent for %s", service.service_name)
            return True
        except Exception as exc:
            # Never log SMTP settings, the password, the recipient, or the message body.
            reason = self._describe(exc)
            logger.warning("SMTP STOPPED alert failed for service %s: %s (%s)", service.service_name, reason, type(exc).__name__)
            self.last_error = f"Last STOPPED alert email failed: {reason} ({type(exc).__name__}). Monitoring continues."
            return False

    @staticmethod
    def _describe(exc: Exception) -> str:
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            return "SMTP authentication rejected; check SMTP_USERNAME and the Gmail App Password"
        if isinstance(exc, smtplib.SMTPRecipientsRefused):
            return "recipient refused; check ALERT_TO"
        if isinstance(exc, smtplib.SMTPSenderRefused):
            return "sender refused; check ALERT_FROM"
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return "SMTP server timed out"
        if isinstance(exc, smtplib.SMTPException):
            return "SMTP error"
        if isinstance(exc, OSError):
            return "SMTP connection failed"
        return "unexpected email error"
