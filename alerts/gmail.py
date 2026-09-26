"""Gmail STARTTLS STOPPED-transition alerts. Credentials are environment-only."""
from email.message import EmailMessage
import logging
import smtplib
import socket
import ssl
from collections.abc import Callable

from app.config import Settings
from app.models import ServiceObservation

logger = logging.getLogger(__name__)


class GmailStoppedAlert:
    def __init__(self, settings: Settings, smtp_factory: Callable = smtplib.SMTP):
        self.settings = settings
        self.smtp_factory = smtp_factory
        self.warning: str | None = None if settings.smtp_configured else "SMTP STOPPED alerts are not configured. Add a Gmail App Password to .env to enable them."

    def send(self, service: ServiceObservation, previous_status: str) -> bool:
        if not self.settings.smtp_configured:
            self.warning = "SMTP STOPPED alerts are not configured. Add a Gmail App Password to .env to enable them."
            return False
        hostname = socket.gethostname()
        detected = service.last_checked.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        message = EmailMessage()
        message["From"] = self.settings.alert_from
        message["To"] = self.settings.alert_to
        message["Subject"] = f"[ALERT] Service STOPPED - {service.service_name} on {hostname}"
        message.set_content(
            "ALERT: Windows Service Stopped\n\n"
            "Application: Kepware Server Monitor\n"
            f"Server: {hostname}\nService: {service.service_name}\nDisplay Name: {service.display_name}\n"
            f"Previous Status: {previous_status}\nCurrent Status: {service.status}\nDetected At: {detected}\n\n"
            "The service changed from RUNNING to STOPPED. Please investigate the service.\n"
        )
        try:
            with self.smtp_factory(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(message)
            self.warning = None
            return True
        except (OSError, smtplib.SMTPException) as exc:
            # Never log SMTP settings, the password, or the message body.
            logger.warning("SMTP STOPPED alert failed for service %s (%s)", service.service_name, type(exc).__name__)
            self.warning = f"SMTP STOPPED alert failed ({type(exc).__name__}); monitoring will continue."
            return False
