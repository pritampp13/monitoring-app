from functools import lru_cache
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)
    mssql_server: str = ""
    mssql_database: str = ""
    mssql_username: str = ""
    mssql_password: str = ""
    mssql_driver: str = "ODBC Driver 18 for SQL Server"
    mssql_trusted_connection: bool = True
    mssql_trust_server_certificate: bool = True
    monitor_interval_seconds: int = 15
    snapshot_interval_minutes: int = 15
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    alert_from: str = ""
    # ALERT_TO is the original name; ALERT_RECIPIENT is accepted as an alias.
    alert_to: str = Field("", validation_alias=AliasChoices("alert_to", "alert_recipient"))
    # Initial email kill-switch position; a dashboard toggle persisted in data/ overrides it.
    email_alerts_enabled: bool = True

    @property
    def database_configured(self) -> bool:
        return bool(self.mssql_server and self.mssql_database)

    @property
    def smtp_missing(self) -> list[str]:
        """Names (never values) of SMTP settings that are empty or still a <placeholder>."""
        required = {"SMTP_HOST": self.smtp_host, "SMTP_USERNAME": self.smtp_username, "SMTP_PASSWORD": self.smtp_password,
                    "ALERT_FROM": self.alert_from, "ALERT_TO": self.alert_to}
        return [name for name, value in required.items() if not value.strip() or value.strip().startswith("<")]

    @property
    def smtp_configured(self) -> bool:
        return not self.smtp_missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
