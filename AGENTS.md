# Kepware EX Service Monitoring Dashboard

## Purpose

This is a local, read-only FastAPI dashboard for monitoring the real Windows
services installed with Kepware Server / KepwareEX. It must never fabricate a
service state or control a service.

## Architecture and stack

- Python 3.14, FastAPI, Uvicorn, Pydantic Settings, and pyodbc.
- Windows Service Control Manager is queried through PowerShell/CIM; no
  Kepware API is assumed or used unless it is locally verified in a future
  change.
- Server-rendered HTML, CSS, and vanilla JavaScript provide the dashboard.
- Optional Microsoft SQL Server persistence is isolated in `app/database.py`.

## Service discovery and status

- Discover only services whose actual Windows `Name` or `DisplayName` contains
  `Kepware` or `KepServer` (case-insensitive).
- Return the SCM service name, display name, state, and start mode exactly as
  supplied by Windows, normalized only to documented state labels.
- Treat a configured/discovered service missing from SCM as `UNKNOWN`; do not
  invent a replacement or sample.
- The monitor collects on a 15-second default interval. It is read-only: never
  start, stop, restart, pause, or reconfigure any service.

## MSSQL configuration and persistence

- Read all MSSQL settings from `.env` / environment variables. Never hardcode
  server names, usernames, passwords, or connection strings containing secrets.
- Database use is optional. If unavailable or unconfigured, monitoring and APIs
  continue and surface an accurate database warning.
- `database/schema.sql` defines `ServiceDefinitions` and
  `ServiceStatusHistory`. Store genuine observations only; record changes and
  periodic snapshots rather than every polling cycle.

## Gmail STOPPED alerts

- Gmail SMTP uses STARTTLS on `smtp.gmail.com:587`; all SMTP values, especially
  `SMTP_PASSWORD`, are read solely from `.env`. The password must be a Gmail App
  Password, never a normal Gmail password.
- Send exactly one email only for a `RUNNING` to `STOPPED` transition. Do not
  alert on repeated STOPPED polls, STOPPED to RUNNING, initial discovery, or
  unverified/missing states.
- Restore prior state from genuine MSSQL history when available; otherwise the
  first observation is a baseline. SMTP failures must not stop monitoring and
  must never cause credentials to be logged or exposed.

## Windows Service

- Production runs through the WinSW-based `KepwareMonitoring` Windows service,
  not a VS Code terminal. It starts automatically and restarts on failure.
- Use the scripts in `scripts/` for install, start, stop, restart, status, and
  uninstall. Keep dashboard binding local to `127.0.0.1`.

## API

- `GET /api/health` reports monitor and database health.
- `GET /api/services` returns current real service observations.
- `GET /api/services/{service_name}/history` returns persisted real history.
- APIs must not return fabricated examples, seeded states, or mock production
  data.

## Frontend

- Bind locally by default and refresh data asynchronously every 15 seconds
  without a full page load.
- Use a professional dark, high-density, responsive design inspired by modern
  developer tools but do not copy third-party branding.
- Clearly distinguish running, stopped, warning/unknown, monitor errors, and
  database persistence warnings. State no history explicitly.

## Testing and security

- Test discovery, status parsing, missing-service handling, health and service
  endpoints, and MSSQL failure handling. Tests may mock OS/database boundaries
  only; production data must remain real.
- Keep v1 localhost-only and read-only. Do not expose credentials, alter
  Windows security, or add public/network deployment features.
- `.env` is required to stay ignored by Git and credentials must never appear in
  source, frontend responses, exception details, or logs.

## Change rule

Inspect this `AGENTS.md` before making future changes and follow these rules.
