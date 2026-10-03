"use strict";
/* Kepware Server Monitor dashboard. Renders only real API data; never invents states. */
const $ = id => document.getElementById(id);
const INTERVAL = (window.MONITOR_INTERVAL || 15) * 1000, HOUR = 36e5, WINDOW_HOURS = 24, HOLD_MS = 1500;
const COLOR = {RUNNING: "#2ef2a0", STOPPED: "#ff4d6d", OTHER: "#ffb547"};
const colorOf = s => s === "RUNNING" ? COLOR.RUNNING : s === "STOPPED" ? COLOR.STOPPED : COLOR.OTHER;
const kind = s => s === "RUNNING" ? "running" : s === "STOPPED" ? "stopped" : "other";
const safe = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const time = v => v ? new Date(v).toLocaleString() : "—";
const clockTime = v => new Date(v).toLocaleTimeString([], {hour12: false});
const pct = v => v == null ? "—" : (v >= 99.95 ? "100" : v.toFixed(1)) + "%";
const dur = ms => { if (ms == null) return "—"; const m = Math.floor(ms / 6e4); if (m < 1) return "<1m"; if (m < 60) return m + "m"; const h = Math.floor(m / 60); if (h < 48) return `${h}h ${String(m % 60).padStart(2, "0")}m`; return `${Math.floor(h / 24)}d ${h % 24}h`; };
const ago = ms => ms >= HOUR ? "-" + (ms / HOUR).toFixed(ms < 10 * HOUR ? 1 : 0).replace(/\.0$/, "") + "h" : "-" + Math.round(ms / 6e4) + "m";
const ICON_HISTORY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M3 4v4h4M12 7v5l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const state = {services: [], counts: null, history: null, health: null, email: null, lastOk: null, online: null};

async function getJSON(url, options) {
  const response = await fetch(url, {cache: "no-store", ...options});
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

/* ---------- Timeline maths shared by row strips, hover graph and history modal ---------- */
function toPoints(records, live) {
  const pts = (records || []).map(x => ({status: x.status, t: Date.parse(x.checked_at)})).filter(x => !isNaN(x.t)).sort((a, b) => a.t - b.t);
  if (live && live.last_checked) {  // extend with the live observation if it is newer than the last stored change
    const t = Date.parse(live.last_checked), last = pts.at(-1);
    if (!last || (last.status !== live.status && t > last.t)) pts.push({status: live.status, t});
  }
  return pts;
}
const liveOf = name => state.services.find(s => s.service_name === name);
const pointsFor = name => toPoints(state.history?.services?.[name], liveOf(name));
function zoomWindow(pointLists) {  // up to 24 h, zoomed to observed data, never narrower than 1 h
  const end = Date.now();
  let first = end;
  pointLists.forEach(p => { if (p.length && p[0].t < first) first = p[0].t; });
  return {start: Math.max(end - WINDOW_HOURS * HOUR, Math.min(first, end - HOUR)), end};
}
function segments(pts, start, end) {
  const out = [];
  pts.forEach((x, i) => {
    const a = Math.max(x.t, start), b = Math.min(i + 1 < pts.length ? pts[i + 1].t : end, end);
    if (b <= a) return;
    const prev = out.at(-1);  // merge snapshot rows that continue the same state
    if (prev && prev.status === x.status && prev.b === a) prev.b = b; else out.push({status: x.status, a, b});
  });
  return out;
}
function stats(pts, win) {
  let run = 0, known = 0, changes = 0, lastChange = null;
  segments(pts, win.start, win.end).forEach(s => { known += s.b - s.a; if (s.status === "RUNNING") run += s.b - s.a; });
  pts.forEach((x, i) => { if (i && pts[i - 1].status !== x.status) { lastChange = x.t; if (x.t >= win.start) changes++; } });
  const inState = lastChange ? win.end - lastChange : pts.length ? win.end - pts[0].t : null;
  return {run, known, changes, lastChange, inState, inStateLowerBound: !lastChange, uptime: known ? run / known * 100 : null};
}

function stripSVG(pts, win) {
  const W = 240, H = 14, X = t => (t - win.start) / (win.end - win.start) * W;
  const bars = segments(pts, win.start, win.end).map(s => `<rect x="${X(s.a).toFixed(2)}" y="1" width="${Math.max(X(s.b) - X(s.a), .9).toFixed(2)}" height="${H - 2}" rx="1.5" fill="${colorOf(s.status)}" opacity=".88"/>`).join("");
  return `<svg class="strip" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><rect class="strip-bg" width="${W}" height="${H}" rx="3"/>${bars}</svg>`;
}

function stepChart(pts, win, {W = 364, H = 136, id = "c"} = {}) {
  const L = 54, R = 12, T = 12, B = 22, iw = W - L - R, ih = H - T - B;
  const X = t => L + (t - win.start) / (win.end - win.start) * iw;
  const Y = s => s === "RUNNING" ? T + 6 : s === "STOPPED" ? T + ih - 6 : T + ih / 2;
  const segs = segments(pts, win.start, win.end);
  const defs = ["RUNNING", "STOPPED", "OTHER"].map(k => `<linearGradient id="${id}-${k}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${COLOR[k]}" stop-opacity=".38"/><stop offset="1" stop-color="${COLOR[k]}" stop-opacity="0"/></linearGradient>`).join("");
  const grid = [["RUNNING", "RUN"], ["OTHER", "OTHER"], ["STOPPED", "STOP"]].map(([k, label]) => `<line class="ch-grid dash" x1="${L}" x2="${W - R}" y1="${Y(k)}" y2="${Y(k)}"/><text class="ch-label" x="${L - 8}" y="${Y(k) + 3}" text-anchor="end" fill="${COLOR[k]}">${label}</text>`).join("");
  const firstData = segs.length ? segs[0].a : win.end;
  const nodata = firstData > win.start ? `<rect class="ch-nodata" x="${L}" y="${T}" width="${(X(firstData) - L).toFixed(1)}" height="${ih}"/><text class="ch-tick" x="${((L + X(firstData)) / 2).toFixed(1)}" y="${T + ih / 2 + 3}" text-anchor="middle">${X(firstData) - L > 46 ? "NO DATA" : ""}</text>` : "";
  const areas = segs.map(s => { const k = s.status in COLOR ? s.status : "OTHER"; return `<rect x="${X(s.a).toFixed(1)}" y="${Y(s.status)}" width="${Math.max(X(s.b) - X(s.a), .8).toFixed(1)}" height="${(T + ih - Y(s.status)).toFixed(1)}" fill="url(#${id}-${k})"/>`; }).join("");
  const joins = segs.slice(1).map((s, i) => `<line class="ch-join" x1="${X(s.a).toFixed(1)}" x2="${X(s.a).toFixed(1)}" y1="${Y(segs[i].status)}" y2="${Y(s.status)}"/>`).join("");
  const lines = segs.map(s => `<line class="ch-seg" x1="${X(s.a).toFixed(1)}" x2="${Math.max(X(s.b), X(s.a) + .8).toFixed(1)}" y1="${Y(s.status)}" y2="${Y(s.status)}" stroke="${colorOf(s.status)}"><title>${safe(s.status)} · ${safe(time(s.a))} → ${safe(time(s.b))}</title></line>`).join("");
  const dots = segs.slice(1).filter((s, i) => s.status !== segs[i].status).map(s => `<circle class="ch-dot" cx="${X(s.a).toFixed(1)}" cy="${Y(s.status)}" r="3.4" fill="${colorOf(s.status)}"><title>${safe(s.status)} at ${safe(time(s.a))}</title></circle>`).join("");
  const last = segs.at(-1);
  const now = last ? `<circle class="ch-now" cx="${X(win.end).toFixed(1)}" cy="${Y(last.status)}" r="4" fill="${colorOf(last.status)}"/><circle cx="${X(win.end).toFixed(1)}" cy="${Y(last.status)}" r="3.2" fill="${colorOf(last.status)}"/>` : "";
  const ticks = [0, .25, .5, .75, 1].map(f => `<line class="ch-grid" x1="${(L + f * iw).toFixed(1)}" x2="${(L + f * iw).toFixed(1)}" y1="${T}" y2="${T + ih}" opacity=".5"/><text class="ch-tick" x="${(L + f * iw).toFixed(1)}" y="${H - 6}" text-anchor="${f === 0 ? "start" : f === 1 ? "end" : "middle"}">${f === 1 ? "NOW" : ago((1 - f) * (win.end - win.start))}</text>`).join("");
  return `<svg class="${id === "hist" ? "hist-chart" : "pop-chart"}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Status over time"><defs>${defs}</defs>${ticks}${grid}${nodata}${areas}${joins}${lines}${dots}${now}</svg>`;
}

/* ---------- Main render ---------- */
function render(data) {
  const c = data.counts, total = c.total || 0;
  state.services = data.services; state.counts = c;
  $("total").textContent = c.total; $("running").textContent = c.running; $("stopped").textContent = c.stopped; $("warning").textContent = c.warning;
  $("m-total").style.width = total ? "100%" : "0";
  $("m-running").style.width = total ? c.running / total * 100 + "%" : "0";
  $("m-stopped").style.width = total ? c.stopped / total * 100 + "%" : "0";
  $("m-warning").style.width = total ? c.warning / total * 100 + "%" : "0";
  $("running-sub").textContent = total ? `${Math.round(c.running / total * 100)}% of fleet online` : "Online now";
  $("last").textContent = "LAST SCAN " + (data.last_checked ? clockTime(data.last_checked) : "—");

  const lists = data.services.map(s => pointsFor(s.service_name)), win = zoomWindow(lists);
  let run = 0, known = 0;
  lists.forEach(p => { const st = stats(p, win); run += st.run; known += st.known; });
  const avail = known ? run / known * 100 : null;
  $("avail").textContent = pct(avail); $("m-avail").style.width = avail == null ? "0" : avail + "%";
  $("avail-sub").textContent = state.history ? `Observed running time · last ${dur(win.end - win.start)}` : "Waiting for history";
  $("strip-label").textContent = `Timeline · ${dur(win.end - win.start)}`;

  const overall = $("overall");
  overall.className = "overall " + (data.monitor_warning ? "err" : c.stopped || c.warning ? "pending" : "ok");
  $("overall-text").textContent = data.monitor_warning ? "MONITOR ERROR" : c.stopped || c.warning ? "ATTENTION" : "ALL HEALTHY";

  $("services").innerHTML = data.services.length ? data.services.map((s, i) => `
    <div class="mrow s-${kind(s.status)}${s.service_name === pop.name ? " hovered" : ""}" data-hover-service="${safe(s.service_name)}">
      <span class="led"></span>
      <div class="mname"><strong>${safe(s.display_name)}</strong><code>${safe(s.service_name)}</code></div>
      <span class="badge ${kind(s.status)}">${safe(s.status)}</span>
      <div class="mstrip">${stripSVG(lists[i], win)}</div>
      <span class="mstart">${safe(s.startup_type || "—")}</span>
      <span class="mtime">${s.last_checked ? clockTime(s.last_checked) : "—"}</span>
      <button class="mbtn" type="button" data-service="${safe(s.service_name)}" aria-label="Open history for ${safe(s.display_name)}">${ICON_HISTORY}</button>
    </div>`).join("") : '<p class="empty-state">No Kepware services were discovered from the Windows Service Control Manager.</p>';

  renderReactor(c, avail);
  renderHexGrid(data.services);
  renderEmail(data.email_alerts);
  renderStatusBar(data);
  if (pop.name && !$("service-popover").hidden) drawPopover(pop.name);
}

function renderReactor(c, avail) {
  const total = c.total || 0, circ = 2 * Math.PI * 64;
  let offset = 0;
  const arcs = [["RUNNING", c.running], ["STOPPED", c.stopped], ["OTHER", c.warning]].filter(x => x[1]).map(([k, v]) => {
    const len = total ? v / total * circ : 0, gap = total > v ? 2.5 : 0;
    const arc = `<circle cx="100" cy="100" r="64" fill="none" stroke="${COLOR[k]}" stroke-width="13" stroke-dasharray="${Math.max(len - gap, 0)} ${circ}" stroke-dashoffset="${-offset}" style="filter:drop-shadow(0 0 6px ${COLOR[k]})"/>`;
    offset += len; return arc;
  }).join("");
  const ticks = Array.from({length: 72}, (_, i) => { const a = i / 72 * Math.PI * 2, r1 = 88, r2 = i % 6 ? 91 : 95; return `<line x1="${(100 + r1 * Math.cos(a)).toFixed(2)}" y1="${(100 + r1 * Math.sin(a)).toFixed(2)}" x2="${(100 + r2 * Math.cos(a)).toFixed(2)}" y2="${(100 + r2 * Math.sin(a)).toFixed(2)}" stroke="rgba(120,190,255,${i % 6 ? .18 : .45})" stroke-width="1"/>`; }).join("");
  $("reactor").innerHTML = `<svg viewBox="0 0 200 200" role="img" aria-label="${c.running} running, ${c.stopped} stopped, ${c.warning} attention of ${total}">
    <defs><radialGradient id="core"><stop offset="0" stop-color="rgba(34,228,255,.16)"/><stop offset="1" stop-color="rgba(34,228,255,0)"/></radialGradient></defs>
    <g class="r-spin">${ticks}</g>
    <g class="r-spin rev"><circle cx="100" cy="100" r="80" fill="none" stroke="rgba(143,123,255,.35)" stroke-width="1" stroke-dasharray="2 6 18 6"/></g>
    <circle cx="100" cy="100" r="54" fill="url(#core)"/>
    <g transform="rotate(-90 100 100)"><circle cx="100" cy="100" r="64" fill="none" stroke="#141c30" stroke-width="13"/>${arcs}</g>
    <text x="100" y="99" text-anchor="middle" class="r-big">${c.running}<tspan font-size="16" fill="#56627f">/${total}</tspan></text>
    <text x="100" y="114" text-anchor="middle" class="r-small">ONLINE</text>
    <text x="100" y="128" text-anchor="middle" class="r-avail">${avail == null ? "" : "AVAIL " + pct(avail)}</text></svg>`;
  $("reactor-legend").innerHTML = [["RUNNING", c.running], ["STOPPED", c.stopped], ["ATTENTION", c.warning]].map(([k, v], i) => `<span><i style="background:${Object.values(COLOR)[i]}"></i>${k} ${v}</span>`).join("");
}

function renderHexGrid(services) {
  const short = n => n.replace(/^Kepware Server\s*/i, "").replace(/\sService$/i, "");
  const grid = $("hex-grid");
  grid.style.setProperty("--rows", Math.max(1, Math.ceil(services.length / 4)));
  grid.innerHTML = services.map(s => `<button type="button" class="hex ${kind(s.status)}${s.service_name === pop.name ? " hovered" : ""}" data-service="${safe(s.service_name)}" data-hover-service="${safe(s.service_name)}" aria-label="${safe(s.display_name)}: ${safe(s.status)}. Open history."><span class="hex-label">${safe(short(s.display_name))}</span><span class="hex-state">${safe(s.status)}</span></button>`).join("") || '<p class="empty-state">No services discovered.</p>';
}

function renderStatusBar(data) {
  const set = (id, cls, text) => { const el = $(id); el.className = "sb-item " + cls; el.lastChild.textContent = text; };
  set("sb-scm", data.monitor_warning ? "err" : "ok", data.monitor_warning ? "SCM ERROR" : "SCM LIVE");
  const db = state.health?.database;
  set("sb-db", db === "connected" ? "ok" : db === "unconfigured" ? "" : db ? "warn" : "", db ? "MSSQL " + db.toUpperCase() : "MSSQL —");
  const a = data.email_alerts;
  set("sb-smtp", !a ? "" : !a.enabled ? "" : a.configured && !a.warning ? "ok" : "warn", !a ? "SMTP —" : !a.enabled ? "SMTP MUTED" : a.configured ? (a.warning ? "SMTP ERROR" : "SMTP READY") : "SMTP NOT SET");
  $("sb-poll").textContent = `POLL ${INTERVAL / 1000}S`;
  $("sb-host").textContent = "HOST " + (state.health?.hostname || "—");
  const issues = [data.monitor_warning, data.database_warning, data.alert_warning, state.history && !state.history.available ? state.history.message : null].filter(Boolean);
  const notice = $("notice"); notice.textContent = [...new Set(issues)].join("  ·  "); notice.title = notice.textContent;
}

/* ---------- Refresh loop ---------- */
async function refresh() {
  const [svc, hist, health] = await Promise.allSettled([getJSON("/api/services"), getJSON(`/api/history?hours=${WINDOW_HOURS}`), getJSON("/api/health")]);
  if (svc.status !== "fulfilled") {
    state.online = false; $("sync").className = "sync offline"; $("sync-text").textContent = "OFFLINE · RETRYING";
    $("overall").className = "overall err"; $("overall-text").textContent = "BACKEND OFFLINE";
    $("notice").textContent = "Backend unavailable. Retrying automatically.";
    return;
  }
  if (hist.status === "fulfilled") state.history = hist.value;
  if (health.status === "fulfilled") state.health = health.value;
  state.online = true; state.lastOk = Date.now(); $("sync").className = "sync";
  render(svc.value);
}
function tickClock() {
  const now = new Date();
  $("clock").textContent = clockTime(now);
  $("date").textContent = now.toLocaleDateString([], {weekday: "short", day: "2-digit", month: "short", year: "numeric"});
  if (state.online && state.lastOk) $("sync-text").textContent = `LIVE · SYNC ${Math.round((Date.now() - state.lastOk) / 1000)}S AGO`;
}

/* ---------- Hover popover: graph for the hovered service only ---------- */
const pop = {name: null, timer: null, x: 0, y: 0};
function markHovered() { document.querySelectorAll("[data-hover-service]").forEach(el => el.classList.toggle("hovered", el.dataset.hoverService === pop.name)); }
function placePopover() {
  const p = $("service-popover"), w = p.offsetWidth || 392, h = p.offsetHeight || 260;
  let left = pop.x + 18, top = pop.y + 18;
  if (left + w > innerWidth - 10) left = pop.x - w - 18;
  if (top + h > innerHeight - 10) top = Math.max(10, innerHeight - h - 10);
  p.style.left = Math.max(10, left) + "px"; p.style.top = Math.max(10, top) + "px";
}
function showPopover(name) {
  if (name === pop.name && !$("service-popover").hidden) return;
  clearTimeout(pop.timer);
  pop.name = name; markHovered();
  pop.timer = setTimeout(() => {
    if (pop.name !== name) return;
    const p = $("service-popover");
    drawPopover(name); p.hidden = false; placePopover();
    requestAnimationFrame(() => p.classList.add("visible"));
  }, 90);
}
function hidePopover() {
  clearTimeout(pop.timer); pop.name = null; markHovered();
  const p = $("service-popover"); p.classList.remove("visible"); p.hidden = true;
}
function drawPopover(name) {
  const p = $("service-popover"), s = liveOf(name);
  if (!s) { hidePopover(); return; }
  const k = kind(s.status);
  const head = `<div class="pop-head s-${k}"><span class="led"></span><div class="pop-title"><strong>${safe(s.display_name)}</strong><code>${safe(name)}</code></div><span class="badge ${k}">${safe(s.status)}</span></div>`;
  if (!state.history) { p.innerHTML = head + '<div class="pop-empty">Loading history…</div>'; return; }
  const pts = pointsFor(name), win = zoomWindow([pts]), st = stats(pts, win);
  const source = state.history.source === "memory" ? "LIVE MEMORY · MSSQL UNAVAILABLE" : "MSSQL HISTORY";
  p.innerHTML = head +
    `<div class="pop-stats"><div><span>Uptime</span><b style="color:${st.uptime == null ? "inherit" : st.uptime >= 99 ? COLOR.RUNNING : st.uptime >= 90 ? COLOR.OTHER : COLOR.STOPPED}">${pct(st.uptime)}</b></div>
      <div><span>Changes</span><b>${st.changes}</b></div>
      <div><span>${safe(s.status === "RUNNING" ? "Running for" : s.status === "STOPPED" ? "Stopped for" : "In state")}</span><b>${st.inState == null ? "—" : (st.inStateLowerBound ? "≥ " : "") + dur(st.inState)}</b></div></div>` +
    (pts.length ? stepChart(pts, win, {id: "pop"}) : `<div class="pop-empty">${safe(state.history.message || "No historical data recorded for this service yet.")}</div>`) +
    `<div class="pop-foot"><span>${source}</span><span>WINDOW ${dur(win.end - win.start).toUpperCase()}${st.lastChange ? " · LAST CHANGE " + clockTime(st.lastChange) : ""}</span></div>`;
}
document.addEventListener("pointerover", e => {
  if (e.pointerType === "touch") return;
  const el = e.target.closest?.("[data-hover-service]");
  if (!el || !$("history-panel").hidden || !$("email-dialog").hidden) return;
  pop.x = e.clientX; pop.y = e.clientY;
  showPopover(el.dataset.hoverService);
});
document.addEventListener("pointerout", e => {
  const from = e.target.closest?.("[data-hover-service]");
  if (!from) return;
  const to = e.relatedTarget?.closest?.("[data-hover-service]");
  if (!to || to.dataset.hoverService !== from.dataset.hoverService) hidePopover();
});
document.addEventListener("pointermove", e => {
  pop.x = e.clientX; pop.y = e.clientY;
  if (pop.name && !$("service-popover").hidden) placePopover();
}, {passive: true});
document.addEventListener("focusin", e => {
  const el = e.target.closest?.("[data-hover-service]");
  if (!el) return;
  const r = el.getBoundingClientRect(); pop.x = r.right; pop.y = r.top;
  showPopover(el.dataset.hoverService);
});
document.addEventListener("focusout", e => { if (e.target.closest?.("[data-hover-service]")) hidePopover(); });
window.addEventListener("blur", hidePopover);

/* ---------- Full history modal ---------- */
let selectedService = null, selectedHours = 24;
document.addEventListener("click", e => {
  const b = e.target.closest?.("[data-service]");
  if (b) showHistory(b.dataset.service);
});
async function showHistory(name) {
  hidePopover(); selectedService = name;
  const s = liveOf(name);
  $("history-panel").hidden = false;
  $("history-title").textContent = (s ? s.display_name + " · " : "") + name;
  $("history-chart").className = "history-chart empty"; $("history-chart").textContent = "Loading real observations…";
  $("history-summary").innerHTML = ""; $("history-content").textContent = "";
  try {
    const d = await getJSON(`/api/services/${encodeURIComponent(name)}/history?hours=${selectedHours}`);
    if (selectedService !== name) return;
    const end = Date.now(), win = {start: end - selectedHours * HOUR, end}, pts = toPoints(d.history, liveOf(name)), st = stats(pts, win);
    const chip = (label, value) => `<div class="hs-chip"><span>${label}</span><b>${value}</b></div>`;
    $("history-summary").innerHTML = chip("Observations", d.history.length) + chip("Uptime", pct(st.uptime)) + chip("State changes", st.changes) + chip("Source", d.source === "memory" ? "Live memory" : "MSSQL");
    if (pts.length) { $("history-chart").className = "history-chart"; $("history-chart").innerHTML = stepChart(pts, win, {W: 900, H: 210, id: "hist"}); }
    else { $("history-chart").className = "history-chart empty"; $("history-chart").textContent = d.message || "No historical data available."; }
    $("history-content").innerHTML = (d.message && d.history.length ? `<p class="history-note">${safe(d.message)}</p>` : "") +
      (d.history.map(x => `<div class="hl-row"><span class="badge ${kind(x.status)}">${safe(x.status)}</span><span>${safe(time(x.checked_at))}</span><span>${safe(x.startup_type || "Unknown startup type")}</span></div>`).join("") || (d.history.length ? "" : '<p class="empty-state">No historical data available.</p>'));
  } catch {
    $("history-chart").className = "history-chart empty"; $("history-chart").textContent = "Unable to load history. Select the service again to retry.";
  }
}
document.querySelectorAll("[data-hours]").forEach(b => b.addEventListener("click", () => {
  selectedHours = +b.dataset.hours;
  document.querySelectorAll("[data-hours]").forEach(x => x.classList.toggle("selected", x === b));
  if (selectedService) showHistory(selectedService);
}));
const closeHistory = () => { $("history-panel").hidden = true; selectedService = null; };
$("close-history").addEventListener("click", closeHistory);
$("history-panel").addEventListener("click", e => { if (e.target === $("history-panel")) closeHistory(); });

/* ---------- Email kill switch (email delivery only; monitoring is never affected) ---------- */
function renderEmail(a) {
  if (!a) return;
  state.email = a;
  const b = $("email-switch"), cls = a.enabled ? (a.configured ? "on" : "warn") : "off";
  b.disabled = false; b.className = "email-switch " + cls;
  $("email-state").textContent = a.enabled ? "ON" : "OFF";
  b.setAttribute("aria-label", `Email alerts ${a.enabled ? "on" : "off"}. Open protected email alert control.`);
  b.title = a.enabled ? (a.configured ? "Email alerts ON — STOPPED transitions are emailed. Click to open the protected control." : "Email alerts ON, but SMTP is not fully configured in .env.") : "Email alerts OFF — no alert emails are sent. Monitoring continues. Click to open the protected control.";
  if (!$("email-dialog").hidden && !hold.raf) fillEmailDialog();
}
function fillEmailDialog() {
  const a = state.email; if (!a) return;
  const cls = a.enabled ? (a.configured ? "on" : "warn") : "off";
  $("em-orb").className = "em-orb " + cls;
  $("em-state").textContent = `EMAIL ALERTS ${a.enabled ? "ON" : "OFF"}`;
  $("em-state").style.color = a.enabled ? (a.configured ? COLOR.RUNNING : COLOR.OTHER) : COLOR.STOPPED;
  $("em-desc").textContent = a.enabled ? (a.configured ? "A RUNNING → STOPPED transition sends one email to the configured recipient." : "Alerts are ON but SMTP settings are missing in .env, so emails cannot be delivered.") : "No alert emails are sent. Monitoring and history are still running.";
  $("em-smtp").textContent = a.configured ? "Configured" : "Missing values in .env";
  $("em-last").textContent = a.last_sent_at ? time(a.last_sent_at) : "None since start";
  $("em-supp").textContent = String(a.suppressed_count ?? 0);
  $("em-changed").textContent = a.updated_at ? time(a.updated_at) : "Default from .env";
  $("em-ack-row").hidden = !a.enabled;
  const btn = $("em-hold");
  btn.className = "hold-btn " + (a.enabled ? "danger" : "safe");
  $("em-hold-text").textContent = a.enabled ? "Hold to turn alerts OFF" : "Hold to turn alerts ON";
  updateHoldEnabled();
}
function updateHoldEnabled() { $("em-hold").disabled = !!state.email?.enabled && !$("em-ack").checked; }
function openEmailDialog() {
  if (!state.email) return;
  hidePopover(); $("em-ack").checked = false; fillEmailDialog();
  $("email-dialog").hidden = false; $("em-cancel").focus();
}
function closeEmailDialog() { holdCancel(); $("email-dialog").hidden = true; $("email-switch").focus(); }
const hold = {raf: 0, start: 0};
function holdBegin(e) {
  const b = $("em-hold");
  if (b.disabled || hold.raf || (e.type === "pointerdown" && e.button !== 0)) return;
  e.preventDefault();
  hold.start = performance.now(); b.classList.add("holding");
  const step = now => {
    const p = Math.min((now - hold.start) / HOLD_MS, 1);
    b.style.setProperty("--p", p);
    if (p >= 1) { hold.raf = 0; b.classList.remove("holding"); commitEmail(); return; }
    hold.raf = requestAnimationFrame(step);
  };
  hold.raf = requestAnimationFrame(step);
}
function holdCancel() {
  if (hold.raf) cancelAnimationFrame(hold.raf);
  hold.raf = 0; const b = $("em-hold"); b.classList.remove("holding"); b.style.setProperty("--p", 0);
}
async function commitEmail() {
  const next = !state.email.enabled, b = $("em-hold");
  b.disabled = true; $("em-hold-text").textContent = "Applying…";
  try {
    const a = await getJSON("/api/alerts/email", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: next})});
    renderEmail(a); $("email-dialog").hidden = true; holdCancel();
    toast(`EMAIL ALERTS ${a.enabled ? "ON" : "OFF"} · monitoring continues`, a.enabled ? "ok" : "bad");
    refresh();
  } catch {
    holdCancel(); fillEmailDialog(); toast("Could not change the email alert setting", "bad");
  }
}
let toastTimer = 0;
function toast(text, cls) {
  const t = $("toast"); t.textContent = text; t.className = "toast show " + cls;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = "toast " + cls; }, 3200);
}
$("email-switch").addEventListener("click", openEmailDialog);
$("em-close").addEventListener("click", closeEmailDialog);
$("em-cancel").addEventListener("click", closeEmailDialog);
$("email-dialog").addEventListener("click", e => { if (e.target === $("email-dialog")) closeEmailDialog(); });
$("em-ack").addEventListener("change", updateHoldEnabled);
const holdBtn = $("em-hold");
holdBtn.addEventListener("pointerdown", holdBegin);
["pointerup", "pointerleave", "pointercancel"].forEach(t => holdBtn.addEventListener(t, holdCancel));
holdBtn.addEventListener("keydown", e => { if ((e.key === " " || e.key === "Enter") && !e.repeat) holdBegin(e); });
holdBtn.addEventListener("keyup", e => { if (e.key === " " || e.key === "Enter") holdCancel(); });
holdBtn.addEventListener("contextmenu", e => e.preventDefault());

document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  hidePopover();
  if (!$("email-dialog").hidden) closeEmailDialog();
  else if (!$("history-panel").hidden) closeHistory();
});

tickClock(); setInterval(tickClock, 1000);
refresh(); setInterval(refresh, INTERVAL);
