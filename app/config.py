from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
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
    alert_to: str = ""

    @property
    def database_configured(self) -> bool:
        return bool(self.mssql_server and self.mssql_database)

    @property
    def smtp_configured(self) -> bool:
        password = self.smtp_password.strip()
        return bool(self.smtp_host and self.smtp_username and self.alert_from and self.alert_to and password and not password.startswith("<"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
