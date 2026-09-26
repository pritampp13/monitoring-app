"""Optional MSSQL persistence. Failures never interrupt service monitoring."""
from datetime import datetime, timedelta, timezone
import socket
from app.config import Settings
from app.models import ServiceObservation


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.warning: str | None = None

    def _connection_string(self) -> str:
        s = self.settings
        parts = [f"DRIVER={{{s.mssql_driver}}}", f"SERVER={s.mssql_server}", f"DATABASE={s.mssql_database}", "Encrypt=yes"]
        if s.mssql_trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            parts.extend([f"UID={s.mssql_username}", f"PWD={s.mssql_password}"])
        if s.mssql_trust_server_certificate:
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts)

    def _connect(self):
        import pyodbc
        return pyodbc.connect(self._connection_string(), timeout=5)

    def check(self) -> bool:
        if not self.settings.database_configured:
            self.warning = "MSSQL is not configured; monitoring is running without persistence."
            return False
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            self.warning = None
            return True
        except Exception as exc:
            self.warning = f"MSSQL unavailable: {type(exc).__name__}. Retrying automatically."
            return False

    def record(self, observations: list[ServiceObservation]) -> None:
        if not observations or not self.check():
            return
        try:
            hostname = socket.gethostname()
            snapshot_cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.settings.snapshot_interval_minutes)
            with self._connect() as conn:
                cursor = conn.cursor()
                for item in observations:
                    cursor.execute("""
                        MERGE dbo.ServiceDefinitions AS target USING (SELECT ? AS service_name, ? AS display_name) AS src
                        ON target.service_name = src.service_name
                        WHEN MATCHED THEN UPDATE SET display_name = src.display_name, enabled = 1
                        WHEN NOT MATCHED THEN INSERT (service_name, display_name) VALUES (src.service_name, src.display_name);
                    """, item.service_name, item.display_name)
                    row = cursor.execute("SELECT id FROM dbo.ServiceDefinitions WHERE service_name = ?", item.service_name).fetchone()
                    previous = cursor.execute("SELECT TOP 1 status, checked_at FROM dbo.ServiceStatusHistory WHERE service_id = ? ORDER BY checked_at DESC", row.id).fetchone()
                    changed = previous is None or previous.status != item.status
                    due = previous is None or previous.checked_at.replace(tzinfo=timezone.utc) <= snapshot_cutoff
                    if changed or due:
                        cursor.execute("INSERT INTO dbo.ServiceStatusHistory (service_id,status,startup_type,checked_at,hostname) VALUES (?,?,?,?,?)", row.id, item.status, item.startup_type, item.last_checked.replace(tzinfo=None), hostname)
                conn.commit()
            self.warning = None
        except Exception as exc:
            self.warning = f"MSSQL persistence failed: {type(exc).__name__}. Retrying automatically."

    def last_known_statuses(self) -> dict[str, str]:
        """Restore genuine status history so restarts do not create false STOPPED alerts."""
        if not self.check():
            return {}
        try:
            with self._connect() as conn:
                rows = conn.execute("""
                    WITH latest AS (
                        SELECT d.service_name, h.status,
                               ROW_NUMBER() OVER (PARTITION BY h.service_id ORDER BY h.checked_at DESC, h.id DESC) AS rn
                        FROM dbo.ServiceStatusHistory h
                        JOIN dbo.ServiceDefinitions d ON d.id = h.service_id
                    ) SELECT service_name, status FROM latest WHERE rn = 1
                """).fetchall()
            return {row.service_name: row.status for row in rows}
        except Exception as exc:
            self.warning = f"MSSQL alert-state read failed: {type(exc).__name__}. Retrying automatically."
            return {}

    def history(self, service_name: str, hours: int) -> list[dict] | None:
        if not self.check():
            return None
        try:
            with self._connect() as conn:
                rows = conn.execute("""SELECT h.status,h.startup_type,h.checked_at,h.hostname FROM dbo.ServiceStatusHistory h JOIN dbo.ServiceDefinitions d ON d.id=h.service_id WHERE d.service_name=? AND h.checked_at >= DATEADD(hour, -?, SYSUTCDATETIME()) ORDER BY h.checked_at DESC""", service_name, hours).fetchall()
            return [{"status": r.status, "startup_type": r.startup_type, "checked_at": r.checked_at.isoformat() + "Z", "hostname": r.hostname} for r in rows]
        except Exception as exc:
            self.warning = f"MSSQL history query failed: {type(exc).__name__}. Retrying automatically."
            return None
