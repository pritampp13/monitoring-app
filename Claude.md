# Claude.md — Kepware Server Monitor

Project context and working rules for Claude Code sessions in this repository.
Read this file before you change anything. It replaces the old `AGENTS.md`, and
every rule from that file is kept under "Non-negotiable rules" below, updated
where later work changed the behaviour.

---

## 1. Project overview

This is a **local, read-only** FastAPI dashboard. It monitors the real Windows
services that Kepware Server / KEPServerEX ("KepwareEX") installs. It:

- reads the services from the Windows Service Control Manager (SCM) through
  PowerShell/CIM (`Get-CimInstance Win32_Service`), not through any Kepware API;
- shows them on a dark, single-page dashboard that refreshes every 15 s by default;
- shows a compact **per-service status graph when you hover** over a service;
- can store genuine state changes and periodic snapshots in Microsoft SQL Server
  (this is optional);
- can send one Gmail SMTP email when a service goes from `RUNNING` to `STOPPED`;
- has a dashboard **email kill switch**, `EMAIL ALERTS: ON/OFF`, that disables
  only the emails;
- runs in production as the `KepwareMonitoring` Windows service, wrapped by WinSW.

It must never fabricate a service state and never control a service.

## 2. Non-negotiable rules

**Read-only and real data**
- Never start, stop, restart, pause or reconfigure any monitored service.
- Never return fabricated examples, seeded states or mock data from the
  application or its APIs.
- Tests may mock only the OS, database and SMTP boundaries.

**Service discovery**
- Discover only services whose actual Windows `Name` or `DisplayName` contains
  `Kepware` or `KepServer` (case-insensitive).
- Return the SCM name, display name, state and start mode as Windows supplies
  them. The state is normalized only to the documented labels (see §6.1).
- If a configured or discovered service is missing from SCM, treat it as
  `UNKNOWN`. Never invent a replacement or sample. (§14 explains how the current
  code actually behaves here.)

**Credentials and secrets**
- All MSSQL and SMTP settings come only from `.env` or environment variables.
  Never hardcode server names, usernames, passwords or connection strings that
  contain secrets.
- Credentials must never appear in source, frontend/API responses, exception
  details, logs, `README.md`, this file, or any git-tracked file.
- `.env` and `data/` must stay git-ignored.

**MSSQL persistence**
- MSSQL is optional. If it is unconfigured or unavailable, monitoring and the
  APIs keep running and show an accurate database warning.
- Store only genuine observations: state changes plus periodic snapshots, not
  every poll.

**Gmail alerts** (details in §7)
- Send exactly one email per stop: a transition from the last *stable* state
  `RUNNING` to `STOPPED`.
- Do not alert on:
  - repeated STOPPED polls
  - STOPPED → RUNNING
  - initial discovery
  - pending/unknown states
  - a service missing from SCM
- Restore the previous state from genuine MSSQL history when it is available.
  Otherwise the first observation is a baseline.
- SMTP failures must not stop or delay monitoring.
- SMTP uses STARTTLS on `smtp.gmail.com:587`. The password must be a Gmail
  **App Password**, never the normal account password.

**Email kill switch** (details in §8)
- It gates **email delivery only**.
- It must never stop polling, status detection, MSSQL writes, history,
  graphs, or the dashboard.

**Network exposure**
- v1 is localhost-only. Bind to `127.0.0.1`.
- Do not add public or network deployment features.
- Do not alter Windows security beyond what the install script already does.

**Production**
- Production runs as the WinSW `KepwareMonitoring` service, not from a VS Code
  terminal. It starts automatically and restarts on failure.
- Use the scripts in `scripts/` to manage it.

**Frontend**
- The frontend clearly distinguishes RUNNING, STOPPED, warning/unknown, monitor
  errors, database persistence warnings and email alert warnings.
- When there is no history, it says so explicitly.

## 3. Repository structure

```
.env.example                    Template for .env — placeholders only, never real addresses/passwords
.gitignore                      Ignores .env, .venv/, __pycache__/, *.py[cod], .pytest_cache/, logs/, data/
README.md                       User-facing setup and run instructions
requirements.txt                Runtime and test dependencies (one file, version ranges)
app/
  main.py                       FastAPI app, lifespan (starts/stops the monitor), file logging, "/" dashboard route
  config.py                     pydantic-settings `Settings` + cached `get_settings()`; SMTP missing-variable check
  models.py                     Pydantic models: ServiceObservation (used), HealthResponse (unused)
  database.py                   Optional MSSQL persistence (pyodbc); the only module that touches SQL
  api/routes.py                 /api/health, /api/services, /api/history, /api/alerts, /api/alerts/email, /api/services/{name}/history
  monitoring/monitor.py         ServiceMonitor: polling loop, stable-state transition detection, alert dispatch, in-memory change history
  services/windows_services.py  PowerShell/CIM SCM query, Kepware filter, state normalization
  templates/index.html          Single Jinja2 page: HUD layout, email control + protected dialog, popover, history modal; cache-busted assets
  static/app.js                 Vanilla JS: refresh loop, timeline maths, matrix/ring/hex render, hover graph, history modal, hold-to-confirm kill switch
  static/style.css              Futuristic dark HUD theme; single-viewport layout; responsive fallbacks
alerts/
  gmail.py                      GmailStoppedAlert: kill-switch gate, message format, STARTTLS send, failure classification
  switch.py                     EmailAlertSwitch: persistent kill switch (data/alert_settings.json)
database/schema.sql             Idempotent DDL for ServiceDefinitions + ServiceStatusHistory
scripts/
  discover_services.ps1         Read-only manual check of which Kepware services SCM reports
  install-service.ps1           Admin: installs WinSW service, grants SQL access to LocalSystem, starts it
  service-control.ps1           start | stop | restart | status | uninstall for KepwareMonitoring
service/
  kepware-monitor.xml.template  WinSW config template (__PYTHON_EXE__, __PROJECT_DIR__ placeholders)
tests/                          pytest tests (see §11)
```

These files are generated at runtime and not tracked:
- `logs/monitor.log`
- `data/alert_settings.json` (the kill-switch state)
- `service/kepware-monitor.exe` and `service/kepware-monitor.xml` (created by
  the install script)
- `.pytest_cache/` and `__pycache__/`

There is no `pyproject.toml`, linter or formatter config, CI pipeline or
Dockerfile.

## 4. Technology stack and dependencies

- **Python 3.14** (3.14.0 installed). The code requires Python ≥ 3.10 (PEP 604
  hints, `asyncio.to_thread`).
- From `requirements.txt` (ranges only; there is no lock file):
  - `fastapi>=0.115,<1`
  - `uvicorn[standard]>=0.30,<1`
  - `pydantic-settings>=2.6,<3`
  - `jinja2>=3.1,<4`
  - `pyodbc>=5.2,<6`
  - `pytest>=8.3,<9` and `httpx>=0.27,<1` (test only)
- Versions observed: fastapi 0.139.0, uvicorn 0.49.0, pyodbc 5.3.0. Packages
  are installed into the global interpreter; there is no venv.
- No frontend libraries or web fonts are loaded (Bahnschrift/Cascadia/Consolas system fonts). Email uses only the standard library (`smtplib`, `ssl`, `email`). No email
  dependency was added.
- OS dependencies:
  - Windows PowerShell (`powershell`) with CIM.
  - Optionally: SQL Server, the "ODBC Driver 18 for SQL Server", `sqlcmd`,
    and WinSW (installed via winget by the install script).
- Frontend: no build step and no third-party JS/CSS. All charts are hand-built
  SVG.

**Do not upgrade or add dependencies unless the task requires it.**

## 5. Architecture and data flow

The layers are kept separate: Monitoring → service state/history → dashboard →
email alerting. The email layer only *consumes* transition events; it never
queries services.

```
 Browser ─GET /─► dashboard HTML (+ /static/app.js, style.css)
   ├─ every MONITOR_INTERVAL s ─► GET /api/services   (in-memory state + email_alerts status)
   ├─ hover a row/hex ─────────► GET /api/services/{name}/history?hours=24  → popover graph
   ├─ "History" click ─────────► same endpoint with 1/6/24/168 h          → modal
   └─ EMAIL ALERTS toggle ─────► PUT /api/alerts/email {"enabled": bool}   → EmailAlertSwitch

 lifespan: configure_logging → Settings → ServiceMonitor(Database, interval, GmailStoppedAlert(settings))
           GmailStoppedAlert builds EmailAlertSwitch(default = EMAIL_ALERTS_ENABLED, file = data/alert_settings.json)
   monitor.start(): restore last stable states from MSSQL → collect() → loop { collect(); sleep(interval) }

 collect():
   discover_kepware_services() (thread) → ServiceObservation list → monitor.services
   for each service:
     _remember()  → in-memory change points (fallback history)
     if status is stable (RUNNING/STOPPED/PAUSED):
        previous stable == RUNNING and now STOPPED → _dispatch_alert() (background task → thread → alerts.send)
        previous_states[name] = status            (also when SMTP fails or alerts are OFF)
   Database.record(services) (thread)
   exception → monitor.error = "Windows service query failed: <Type>" (logged once per error episode)
```

`/api/services` reads only the in-memory monitor state. The history and health
routes run their pyodbc calls with `asyncio.to_thread`, so a slow database
never blocks the event loop.

## 6. Key components (verified from the code)

### 6.1 `app/services/windows_services.py`
- `_read_services()` runs `Get-CimInstance Win32_Service | Select-Object
  Name,DisplayName,State,StartMode | ConvertTo-Json -Compress` through
  `powershell -NoProfile -NonInteractive`, with `check=True` and `timeout=20`.
- `is_kepware_service()` does a case-insensitive substring match for `kepware`
  or `kepserver`.
- `normalize_status()` maps SCM text to one of these labels:
  - `RUNNING`, `STOPPED`, `PAUSED`
  - `START_PENDING`, `STOP_PENDING`, `PAUSE_PENDING`, `CONTINUE_PENDING`
  - Anything else becomes `UNKNOWN`.
- `discover_kepware_services(reader=..., checked_at=...)` returns results
  sorted by display name. The `reader` parameter is how tests inject data.

### 6.2 `app/monitoring/monitor.py` — `ServiceMonitor`
- `STABLE_STATES = {"RUNNING", "STOPPED", "PAUSED"}`. Pending and UNKNOWN
  states never overwrite `_previous_states`.
- `_dispatch_alert()` schedules `alerts.send` as an asyncio task that runs in a
  thread, tracked in `_alert_tasks`. Polling never waits for SMTP, which has a
  15 s timeout.
  - `wait_for_alerts()` lets tests await these tasks.
  - `stop()` waits up to 20 s for in-flight emails.
- `_recent` keeps per-service genuine state-change points: a `deque`,
  maxlen 2000, holding `status`, `startup_type` and the `checked_at` datetime.
- `recent_history(name, hours)` returns those points newest first, plus the
  last change before the window (the state at the window's start). It is the
  history fallback when MSSQL is unavailable.
- Injection points: `discoverer=` and `alerts=`.

### 6.3 `app/database.py` — `Database`
- **This is the only place that talks to MSSQL.** `pyodbc` is imported lazily.
- Connection string:
  - Always includes `Encrypt=yes`.
  - `Trusted_Connection=yes` or `UID`/`PWD`.
  - Adds `TrustServerCertificate=yes` when configured.
  - Login timeout is 5 s.
- `check()` returns False with a "not configured" warning when the server or
  database setting is empty. On failure the warning contains only the
  exception type name.
- `record()`:
  - MERGEs `ServiceDefinitions`.
  - Inserts into `ServiceStatusHistory` when the status changed, or when the
    last row is at least `SNAPSHOT_INTERVAL_MINUTES` old.
  - `checked_at` is stored as naive UTC.
- `last_known_statuses()` returns the latest **stable** status per service
  (`WHERE status IN ('RUNNING','STOPPED','PAUSED')`). This restores alert state
  after a restart, so a stop that happened through STOP_PENDING across a
  restart is still caught.
- `history(name, hours)`:
  - Returns `None` when the database is unavailable.
  - Returns a list otherwise, newest first, with `checked_at` as ISO + `"Z"`.
- Every method catches all exceptions and sets `self.warning`. None of them
  raise.

### 6.4 `alerts/gmail.py` — `GmailStoppedAlert`
See §7.

### 6.5 `alerts/switch.py` — `EmailAlertSwitch`
See §8.

### 6.6 `app/config.py`
- `Settings` reads `.env` **relative to the current working directory**, with
  `extra="ignore"` and `populate_by_name=True`.
- `alert_to` accepts the env names `ALERT_TO` (canonical) and
  `ALERT_RECIPIENT` (alias), via `AliasChoices`.
- `smtp_missing` lists the *names* of SMTP settings that are empty or start
  with `<` (the `.env.example` placeholders). `smtp_configured` is true when
  that list is empty.
- `email_alerts_enabled` gives the initial kill-switch position.
- `get_settings()` is `lru_cache`d, so `.env` changes need a restart.

### 6.7 `app/main.py`
- `configure_logging()` sets INFO level with one `FileHandler`, writing to
  `<repo>/logs/monitor.log`.
- Swagger and ReDoc are disabled. `/openapi.json` is still served.
- `asset_version()` (the newest mtime of `app.js`/`style.css`) is passed to the
  template as `?v=` on both assets. Browsers therefore never mix new HTML with
  cached old JS/CSS. That mix is exactly what broke the toggle and the hover
  graph once, so keep it.

### 6.8 Frontend (`templates/index.html`, `static/app.js`, `static/style.css`)
The UI is a futuristic dark HUD design with vanilla JS and no external
fonts, CDNs or libraries. It works offline on a plant PC.

**Layout.** At >= 960 px wide and >= 620 px tall, the page fits one viewport
(`body{overflow:hidden}`, `.app` is a `100dvh` grid) and never scrolls. Smaller
screens fall back to normal page scrolling. The regions are:
- **Top bar:** brand, the live sync pill ("LIVE · SYNC Ns AGO" / "OFFLINE"), a
  clock, the email kill-switch control, and the overall chip (ALL HEALTHY /
  ATTENTION / MONITOR ERROR / BACKEND OFFLINE).
- **KPI tiles:** Total, Running, Stopped, Attention, and Availability, which is
  observed running time across all services in the timeline window, computed
  client-side from real history.
- **Service matrix:** a row per service with LED, name/ID, state badge, a 24 h
  timeline strip, startup type, checked time, and a History button. Rows flex
  to fill the panel; only the matrix scrolls internally if there are many
  services.
- **Side column:** the "fleet status" ring (state distribution + ONLINE count +
  availability) and the hexagon grid. Hexes size to the available height.
- **Status bar:** SCM / MSSQL (from `/api/health`) / SMTP / poll / host chips,
  plus a right-aligned notice that joins the monitor, database, alert and
  history warnings.

**Refresh.** Every `MONITOR_INTERVAL` s, `refresh()` fetches
`/api/services`, `/api/history?hours=24` and `/api/health` in parallel. Only a
`/api/services` failure marks the dashboard offline.

**Shared timeline maths.** `toPoints`, `zoomWindow`, `segments` and `stats`:
- `segments()` merges consecutive same-state rows (snapshots), so strips have
  no seams.
- The window is up to 24 h, zoomed to the observed data, and never narrower
  than 1 h.
- The live status from `/api/services` extends the last segment to "now".
- The same functions feed the row strips, the hover graph and the history
  modal, so they always agree.

**Rules.**
- All server strings pass through `safe()` before being put into `innerHTML`.
  Keep doing this.
- State CSS classes are `running` / `stopped` / `other` (via `kind()`).
- Animations respect `prefers-reduced-motion`.

## 7. Email alert architecture

**Trigger.** The trigger lives in `ServiceMonitor.collect()`.
- It fires when the previous stable state is `RUNNING` and the current one is
  `STOPPED`.
- `_previous_states` is updated for every stable observation, even if SMTP
  fails or alerts are OFF. One transition means one send attempt; there is no
  retry and no backlog.

| Sequence | Emails |
|---|---|
| RUNNING → STOPPED | 1 |
| RUNNING → STOPPED → STOPPED (repeated polls) | 1 |
| RUNNING → STOPPED → RUNNING → STOPPED | 2 |
| RUNNING → STOP_PENDING → STOPPED | 1 |
| STOPPED → START_PENDING → STOPPED (failed start) | 0 |
| First observation is STOPPED (no DB history) | 0 |
| MSSQL last stable state RUNNING, service STOPPED at startup | 1 |
| Alerts OFF during RUNNING → STOPPED | 0 (no email later when switched back ON) |

**Sending.** `GmailStoppedAlert.send(service, previous)` in `alerts/gmail.py`:
1. If the kill switch is OFF, it increments `suppressed_count`, logs at INFO,
   and returns False.
2. If SMTP is not configured, it logs the missing variable *names* and returns
   False.
3. It builds the message:
   - Subject: `KepwareEX Service Stopped - <service_name>`
   - The body starts with `Service Name:`, `Status: STOPPED`, and
     `Stopped At: 03-Oct-2026 15:42:18 (UTC+05:30)` (server-local time).
   - It then adds the display name, server hostname and previous status.
   - "Stopped At" is the observation time of the first poll that saw STOPPED,
     which is within one polling interval of the real stop.
4. It sends over SMTP with a 15 s timeout: `ehlo` → `starttls(default SSL
   context)` → `ehlo` → `login` → `send_message`.
5. On any exception it classifies the failure and logs
   `SMTP STOPPED alert failed for service X: <reason> (<Type>)`. It sets
   `last_error` and returns False. Failure classes:
   - authentication rejected
   - recipient refused
   - sender refused
   - timeout
   - other SMTP error
   - connection failed
   - unexpected error

It never logs or returns the password, the SMTP username, the recipient or the
message body.

**Status for the UI.** `status()` returns `enabled`, `configured`, `warning`,
`last_sent_at`, `updated_at` and `suppressed_count`. The `warning` property
returns:
- `None` when alerts are OFF;
- a missing-variables message (names only) when SMTP is not configured;
- otherwise the last send error or the switch's own warning.

Sender and recipient addresses are never sent to the browser.

## 8. Email kill switch

- **Storage.** `EmailAlertSwitch` (`alerts/switch.py`) stores
  `{"email_alerts_enabled": bool, "updated_at": iso}` in
  `<repo>/data/alert_settings.json`. That directory is git-ignored.
  - It writes atomically (temp file + `os.replace`), under a lock.
  - If the file is missing, it uses `EMAIL_ALERTS_ENABLED` (default true).
  - If the file is unreadable, it uses the env default and sets a warning.
  - If a write fails, the new value still applies in memory and a warning
    says it will reset on restart.
- **Scope.** It is checked only inside `GmailStoppedAlert.send()`. The monitor
  loop, transition tracking, MSSQL writes, history and graphs never read it.
- **API.**
  - `GET /api/alerts` returns the status.
  - `PUT /api/alerts/email` with JSON `{"enabled": true|false}` changes it.
- **Write protection.** There is no login (localhost-only v1), so the PUT is
  guarded instead. It requires:
  - a JSON body (FastAPI rejects form posts with 422);
  - a `Host` of `127.0.0.1`, `localhost` or `::1`, which blocks DNS rebinding;
  - an `Origin`, when one is present, equal to the `Host`, which blocks
    cross-site requests.
  If authentication is ever added, this endpoint must require an administrator.
- **UI and accidental-change protection.**
  - The top-bar control shows a mail icon, `EMAIL ALERTS` with `ON`/`OFF`, a
    sliding switch, and a lock icon. Green means ON, red means OFF, and amber
    means ON but SMTP is not configured.
  - **A click never changes anything.** It only opens the "Email alert kill
    switch" dialog. The dialog shows the state, whether SMTP is configured,
    the last alert sent, the suppressed count, and when the switch last
    changed, plus a note on scope.
  - Turning alerts **OFF** requires ticking an acknowledgement checkbox. The
    hold button stays disabled until it is ticked.
  - Both directions require **pressing and holding** the button for
    `HOLD_MS` = 1.5 s, with a fill animation. Releasing early, moving the
    pointer off, or pressing Escape cancels. Space or Enter held down also
    works.
  - On success the dialog closes, a toast says "EMAIL ALERTS OFF · monitoring
    continues", and the status bar shows `SMTP MUTED`.

## 9. Service hover graph

- **Trigger.**
  - `pointerover` on any `[data-hover-service]` element (matrix rows, hexes)
    or keyboard focus shows `#service-popover` after 90 ms. The hovered
    service's row and hex get a `.hovered` highlight.
  - The popover is 392 px wide, follows the pointer, and is clamped to the
    viewport.
  - It has `pointer-events: none`, so it never blocks clicks.
  - It hides when the pointer leaves that service, on focus out, Escape,
    window blur, or when a modal opens. Touch pointers are ignored; tapping
    opens History instead.
- **Data.** No request is made per hover. The popover reads the batched
  `/api/history` data already loaded by `refresh()`, so it appears instantly.
  It redraws on every refresh while open and keeps tracking the same service
  across re-renders.
- **Graph content** (`drawPopover`):
  - **Header:** LED, display name, service ID, state badge.
  - **Stats:** uptime % (coloured by threshold), number of state changes in
    the window, and "Running for / Stopped for" since the last change (>= when
    no change has been seen).
  - **Step chart** (`stepChart`): RUN / OTHER / STOP lanes, coloured segments
    with gradient areas, dashed transition joins, change dots with tooltips,
    a pulsing "now" marker, a gray "NO DATA" region before the first
    observation, and relative ticks.
  - **Footer:** source ("MSSQL HISTORY" or "LIVE MEMORY · MSSQL UNAVAILABLE"),
    window length, and last change time.
- **Why spans are correct.** Rows are written on every change plus periodic
  snapshots, so drawing each status until the next row is accurate.
- **No MSSQL.** The history endpoints return the monitor's in-memory change
  points (`source: "memory"`), so the graphs still show genuine data observed
  since the process started.
- **History modal.** Clicking a row's History button or a hex opens a larger
  step chart for 1 h / 6 h / 24 h / 7 d, with summary chips and the raw
  observation list. It uses the per-service endpoint.

## 10. HTTP API

| Method & path | Response |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/health` | `{status: "ok"\|"degraded", hostname, monitor_last_checked, database, database_warning, monitor_warning, alert_warning, email_alerts}` |
| `GET /api/services` | `{services, counts: {total, running, stopped, warning}, last_checked, monitor_warning, database_warning, alert_warning, email_alerts}` |
| `GET /api/alerts` | `{enabled, configured, warning, last_sent_at, updated_at, suppressed_count}` |
| `PUT /api/alerts/email` | Body `{"enabled": bool}` → alert status; 403 for non-local Host / cross-origin; 422 for non-JSON |
| `GET /api/history?hours=24` | All services in one query: `{hours, services: {name: [records newest first]}, available, source: "database"\|"memory", message}`; same `hours` rule. Feeds the timelines and hover graphs |
| `GET /api/services/{name}/history?hours=24` | `hours` ∈ {1, 6, 24, 168} else 400. DB OK → `{history, available: true, source: "database", message}`; DB down → `{history: <in-memory changes>, available: false, source: "memory", message}` |

## 11. Configuration (`.env`, see `.env.example`)

| Variable | Default | Notes |
|---|---|---|
| `MSSQL_SERVER`, `MSSQL_DATABASE` | `""` | Either empty → persistence disabled |
| `MSSQL_USERNAME` / `MSSQL_PASSWORD` | `""` | Only when trusted connection is false |
| `MSSQL_DRIVER` | `ODBC Driver 18 for SQL Server` | |
| `MSSQL_TRUSTED_CONNECTION`, `MSSQL_TRUST_SERVER_CERTIFICATE` | `true` | |
| `MONITOR_INTERVAL_SECONDS` | `15` | Backend poll interval *and* frontend refresh interval |
| `SNAPSHOT_INTERVAL_MINUTES` | `15` | Periodic history snapshot cadence |
| `SMTP_HOST` / `SMTP_PORT` | `""` / `587` | Gmail: `smtp.gmail.com` / `587` (STARTTLS) |
| `SMTP_USERNAME` | `""` | Sending Gmail account |
| `SMTP_PASSWORD` | `""` | Gmail **App Password** (16 chars; spaces are display-only) |
| `ALERT_FROM` | `""` | Sender address |
| `ALERT_TO` (alias `ALERT_RECIPIENT`) | `""` | Recipient address |
| `EMAIL_ALERTS_ENABLED` | `true` | Initial kill-switch position; the dashboard toggle (data file) overrides it |

**Configuring safely**
- Put real values only in `.env`, which is git-ignored. `.env` was configured
  for Gmail on 2026-10-03.
- Never print or `cat` `.env`. To inspect it, show key names only, e.g. with
  awk that redacts the values.
- `.env.example` holds placeholders only (`<...>`), and placeholders count as
  "not configured".
- The bind host and port (`127.0.0.1:8000`) are not settings. They are in the
  README command and in `service/kepware-monitor.xml.template`.
- `.env` changes need a restart: `.\scripts\service-control.ps1 restart` or
  restarting uvicorn.

## 12. Running, testing and deploying

### Local
Run from the repo root, because `.env` is resolved from the current working
directory:
```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Then open http://localhost:8000. To check which services SCM reports
(read-only): `.\scripts\discover_services.ps1`.

### Tests
Run `python -m pytest -q`. There are 35 tests, and all passed on 2026-10-03.

| File | Covers |
|---|---|
| `test_windows_services.py` | State normalization, the Kepware filter, and that no services yields an empty list |
| `test_database.py` | Unconfigured DB warning; unavailable host (makes a real pyodbc attempt to `not-a-real-host`) |
| `test_alerts.py` | Every transition rule in §7, message format, STARTTLS, kill switch OFF/ON and persistence, monitoring continuing while OFF, each SMTP failure class, secret redaction in warnings/logs/status, missing-variable names, `ALERT_RECIPIENT` alias |
| `test_api.py` | Two tests use the **real lifespan**; the rest install a fake monitor on `app.state` (no lifespan) to test the kill-switch endpoint, its guards, secret-free responses, per-service and batched history mapping, the in-memory fallbacks, and asset cache-busting |

Tests always pass an `EmailAlertSwitch` with a `tmp_path` file and use
`Settings(_env_file=None, ...)`, so they never read or modify the real switch
file or `.env`.

**Caution:** the two real-lifespan tests in `test_api.py` use the real `.env`.
They run a real SCM query and touch the real MSSQL. They could send a real
email if the restored MSSQL state says RUNNING while a service is now STOPPED.

### How to test email alerts safely
- **Logic.** `python -m pytest -q tests/test_alerts.py` uses a fake SMTP and
  sends no real mail.
- **Credentials only.** Do an SMTP STARTTLS login without sending: run
  `smtplib.SMTP(host, 587)`, `starttls()` and `login()` using `get_settings()`,
  and print only success or the exception type. This was verified OK on
  2026-10-03.
- **Real end-to-end.** This needs a real RUNNING → STOPPED transition of a
  Kepware service, which only an operator may cause; the app never controls
  services. Do this only with the user's explicit permission. Then check the
  inbox and `logs/monitor.log` for "STOPPED alert email sent for <name>".

### Windows service (production)
Run from an **Administrator** PowerShell:
```powershell
.\scripts\install-service.ps1
.\scripts\service-control.ps1 status|start|stop|restart|uninstall
```

The install script:
1. Finds or installs WinSW (via winget).
2. Fills in the XML template with the absolute path of the current `python`
   and the repo directory.
3. Copies WinSW to `service\kepware-monitor.exe`.
4. If MSSQL uses trusted auth, grants `NT AUTHORITY\SYSTEM` the
   `db_datareader` and `db_datawriter` roles via `sqlcmd`.
5. Installs the service with `start= auto` and `sc.exe failure` restart
   actions, then starts it.

The service runs as **LocalSystem** with the repo as its working directory, so
`.env`, `logs/` and `data/` resolve there. `.env` must exist before you
install.

At 2026-10-03, the `KepwareMonitoring` service was **not installed** on this
machine, and MSSQL (`KepwareMonitor`) was reachable and holding history.

## 13. Coding conventions

- **Python style.** Compact: long single-line expressions and short methods.
  Match it, and don't reformat whole files.
- **Frontend style.** `app.js` and `style.css` were rebuilt as readable,
  sectioned code (CSS uses `:root` tokens). Keep that structure.
- PEP 604 unions (`str | None`).
- **Dependency injection for boundaries.** `reader=`, `discoverer=`,
  `alerts=`, `smtp_factory=`, `switch=`. Tests use fakes for these, not
  patching.
- **Errors become warning strings**, not exceptions. User-visible messages and
  logs include only `type(exc).__name__` and fixed text, never `str(exc)`. This
  keeps credentials and connection strings from leaking.
- Blocking I/O from async code goes through `asyncio.to_thread`.
- Status labels are upper-case SCM strings, and the CSS classes depend on them.

## 14. Known gaps and technical debt

Do not fix these casually.

1. **"Missing service → UNKNOWN" is not implemented as written.**
   - A service that disappears from SCM just drops out of `monitor.services`,
     with no alert.
   - `ServiceDefinitions.enabled` is never cleared or read.
2. **The in-memory history fallback resets on restart.** It also only contains
   points observed by this process.
3. **`HealthResponse` in `app/models.py` is unused** and doesn't match the real
   payload.
4. **`Database.check()` opens a fresh connection** for every health and
   history request and before every DB operation. pyodbc's `with` commits or
   rolls back but is not documented to close the connection.
5. **Restart policy is defined twice.** WinSW `<onfailure>` (10/20/30 s) and
   `sc.exe failure` (10/10/30 s).
6. **`.gitignore` has duplicated entries.**
7. **Only alert, switch and monitor-error events go to `logs/monitor.log`.**
   Uvicorn logs go to stdout. Where WinSW keeps the service's stdout and
   stderr was not verified.
8. **`requirements.txt` mixes runtime and test dependencies**, and there is no
   lock file.
9. **There is no authentication.** The kill-switch PUT relies on the
   localhost/origin guard (§8).
10. **There is no retry or queue for failed alert emails.** This is by design:
    one transition means one attempt.
11. **Test warning.** The test client emits a Starlette "use httpx2"
    deprecation warning; this comes from the environment.

## 15. Troubleshooting

- **No services shown.** Run `.\scripts\discover_services.ps1`, and check that
  PowerShell/CIM works for the account running the app (LocalSystem when it
  runs as a service).
- **"MONITOR ERROR".** The CIM query failed or timed out (20 s). It is logged
  once per episode.
- **Database warning.**
  - "not configured" means `MSSQL_SERVER`/`MSSQL_DATABASE` is empty.
  - "unavailable" means a driver, network, authentication or certificate
    problem.
  - Check that `database/schema.sql` was applied.
- **`EMAIL ALERTS: ON` shown in amber.** SMTP is not configured; the notice
  names the missing variables.
- **No alert email.** Check `alert_warning` / `GET /api/alerts`, then the
  `logs/monitor.log` lines:
  - `SMTP authentication rejected` means a wrong username or App Password, or
    2-Step Verification/App Passwords are disabled on the Google account.
  - `timed out` or `connection failed` means network, firewall or port 587
    problems.
  - `Email alerts are OFF` means the kill switch is off.
  - Alerts fire only on an observed RUNNING → STOPPED transition.
- **Kill switch resets on restart.** `data/` is not writable for the service
  account; the UI warning says so.
- **`.env` changes are not applied.** Settings are cached; restart the process
  or the service.
- **Wrong Python in the service.** The python path is baked in at install
  time; uninstall and reinstall.

## 16. Guidance for future Claude Code sessions

- Read this file first, and keep it accurate when you change behaviour.
- Never add code that starts, stops or reconfigures monitored services, and
  never add demo, seed or fallback data to production paths.
- Never print, log, return or commit secrets.
  - Do not `cat` `.env`.
  - Never copy the SMTP password into any tracked file, including this one.
- The kill switch must remain email-only. Do not route it into
  `ServiceMonitor` or `Database`.
- Preserve the alert semantics in §7; `tests/test_alerts.py` encodes them.
- Keep MSSQL access in `app/database.py`, and keep the schema and the queries
  in sync.
- Do not send real test emails or cause real service state changes without
  the user's explicit permission.
- Do not run `install-service.ps1` or `service-control.ps1` unless asked.
- Do not upgrade dependencies or restructure the project unless asked.

### Unknowns
- Where WinSW writes the service's stdout/stderr logs.
- Any CI/CD or release process; none is present.
- Multi-host use; the design is single-host, with `hostname` recorded per row.
