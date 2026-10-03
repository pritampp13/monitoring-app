# Kepware Server Monitor

Local, read-only monitoring for actual Kepware Windows services. It queries the
Windows Service Control Manager; it does not use, assume, or control a Kepware
API.

## Requirements

- Windows with Python 3.14 (or a supported Python version)
- Permission to read Windows services
- Optional: SQL Server and ODBC Driver 18 for SQL Server for history

## Install and start

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://localhost:8000>. The server is bound to `127.0.0.1` by default.

## SQL Server history (optional)

Create a database through your approved SQL Server administration process, then
run `database/schema.sql` against that database. Set `MSSQL_SERVER` and
`MSSQL_DATABASE` in `.env`; use Windows authentication by default or set
`MSSQL_TRUSTED_CONNECTION=false` and supply username/password through the
environment. Do not commit `.env`.

The monitor remains live if MSSQL is absent or temporarily unavailable. It
records real state changes plus a periodic health snapshot (15 minutes by
default), not every poll.

## Discovery and troubleshooting

The monitor dynamically selects Windows services where the actual `Name` or
`DisplayName` contains `Kepware` or `KepServer`. Run this read-only inspection:

```powershell
.\scripts\discover_services.ps1
```

If no services appear, verify Kepware is installed under the account running
the dashboard and that PowerShell/CIM is available. The dashboard never shows
sample states: no discovered services means it displays that fact explicitly.

Run tests with `python -m pytest -q`.

## Gmail STOPPED alerts

The application only sends a mail after a real `RUNNING → STOPPED` transition
(a stop observed through `STOP_PENDING` counts once). Repeated STOPPED checks and
STOPPED → RUNNING do not send mail; a later new stop sends a new mail. The email
subject is `KepwareEX Service Stopped - <service>` and the body lists the service
name, status, and the time the stop was observed.

Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_FROM`
and `ALERT_TO` (or `ALERT_RECIPIENT`) in `.env` only. `SMTP_PASSWORD` must be a
Gmail App Password (not a normal Gmail password); SMTP uses `smtp.gmail.com:587`
with STARTTLS. The recipient, sender, and all SMTP values remain server-side and
are never sent to the dashboard. SMTP failures are logged to `logs/monitor.log`
without credentials and never stop monitoring.

The dashboard header shows **EMAIL ALERTS: ON/OFF**. Clicking it is a kill switch
for emails only: monitoring, history, graphs and the dashboard keep running. The
choice is saved in `data/alert_settings.json` (git-ignored); `EMAIL_ALERTS_ENABLED`
in `.env` sets the initial value.

Hover over a service row or hexagon to see a small status timeline for that
service from its recorded history.

## Run continuously as a Windows service

Open **Administrator PowerShell** in this project and install the service once:

```powershell
.\scripts\install-service.ps1
```

This installs the automatic, crash-restarting `KepwareMonitoring` service via
WinSW, grants its LocalSystem identity only reader/writer access to the
configured monitor database, and starts the dashboard on `http://localhost:8000`.
VS Code can then be closed safely.

```powershell
.\scripts\service-control.ps1 status
.\scripts\service-control.ps1 stop
.\scripts\service-control.ps1 start
.\scripts\service-control.ps1 restart
.\scripts\service-control.ps1 uninstall
```
