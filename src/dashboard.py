"""dashboard.py — analytics dashboard HTML + stats API.

GET /dashboard       password-protected analytics page
GET /api/stats       JSON stats (?days=30)
"""
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .store import get_pipeline, get_stats, update_lead

security = HTTPBasic(auto_error=False)


def check_auth(creds: HTTPBasicCredentials = Depends(security)):
    user = os.getenv("DASHBOARD_USER", "admin")
    pw = os.getenv("DASHBOARD_PASSWORD", "")
    if not pw:
        # No password configured: allow but warn. Set DASHBOARD_PASSWORD
        # in production.
        return True
    if creds is None:
        raise HTTPException(401, "Login required",
                            {"WWW-Authenticate": "Basic"})
    ok_user = secrets.compare_digest(creds.username, user)
    ok_pw = secrets.compare_digest(creds.password, pw)
    if not (ok_user and ok_pw):
        raise HTTPException(401, "Invalid login",
                            {"WWW-Authenticate": "Basic"})
    return True


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Call Analytics — Arizona's Best Equipment</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root { --orange: #e8641b; --charcoal: #23272b; --bg: #f4f5f6; --card: #fff; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--charcoal); }
header { background: var(--charcoal); color: #fff; padding: 1rem 1.5rem; display: flex; justify-content: space-between; align-items: center; }
header h1 { font-size: 1.15rem; }
header h1 span { color: var(--orange); }
.range { display: flex; gap: .5rem; }
.range button { background: #3a4046; color: #fff; border: 0; padding: .4rem .8rem; border-radius: 6px; cursor: pointer; }
.range button.active { background: var(--orange); }
main { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.kpi { background: var(--card); border-radius: 10px; padding: 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.kpi .num { font-size: 2rem; font-weight: 800; color: var(--orange); }
.kpi .lbl { font-size: .8rem; color: #666; text-transform: uppercase; letter-spacing: .04em; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
@media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
.card { background: var(--card); border-radius: 10px; padding: 1.1rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card h2 { font-size: 1rem; margin-bottom: .8rem; }
.card canvas { max-height: 260px; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { text-align: left; padding: .55rem .4rem; border-bottom: 1px solid #eee; }
th { color: #666; font-weight: 600; text-transform: uppercase; font-size: .72rem; }
.pill { display: inline-block; padding: .15rem .55rem; border-radius: 20px; font-size: .75rem; font-weight: 700; }
.pill.down_now { background: #fde8e8; color: #c0392b; }
.pill.safety { background: #fef3e2; color: #b7791f; }
.pill.routine { background: #e8f5e9; color: #2e7d32; }
.empty { text-align: center; color: #888; padding: 3rem 1rem; }
.tabs { display: flex; gap: .5rem; }
.tab { background: #3a4046; color: #fff; border: 0; padding: .5rem 1.1rem; border-radius: 6px; cursor: pointer; font-size: .9rem; }
.tab.active { background: var(--orange); }
.badge { background: #c0392b; color: #fff; border-radius: 12px; padding: .1rem .5rem; font-size: .75rem; font-weight: 700; }
#stale-banner { margin-bottom: 1rem; }
.stale-alert { background: #fde8e8; border: 1px solid #e8a0a0; border-radius: 10px; padding: .9rem 1.1rem; margin-bottom: .6rem; }
.stale-alert strong { color: #c0392b; }
.pipe-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1rem; }
.pipe-col { background: var(--card); border-radius: 10px; padding: .9rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); min-height: 200px; }
.pipe-col h3 { font-size: .85rem; text-transform: uppercase; letter-spacing: .04em; color: #666; margin-bottom: .7rem; display: flex; justify-content: space-between; }
.pipe-col h3 .count { background: #eee; border-radius: 10px; padding: 0 .5rem; }
.lead-card { background: #fafbfc; border: 1px solid #e6e8ea; border-radius: 8px; padding: .7rem; margin-bottom: .6rem; font-size: .82rem; }
.lead-card .nm { font-weight: 700; }
.lead-card .meta { color: #666; margin: .25rem 0; }
.lead-card select, .lead-card textarea { width: 100%; margin-top: .4rem; font: inherit; font-size: .8rem; padding: .35rem; border: 1px solid #ddd; border-radius: 6px; }
.lead-card textarea { min-height: 44px; resize: vertical; }
.lead-card .save-note { margin-top: .3rem; font-size: .75rem; background: var(--charcoal); color: #fff; border: 0; border-radius: 6px; padding: .3rem .7rem; cursor: pointer; }
.lead-card.stale-card { border-color: #e8a0a0; background: #fff8f8; }
</style>
</head>
<body>
<header>
<h1>ARIZONA'S BEST <span>EQUIPMENT</span> — Call Analytics</h1>
<div class="tabs">
<button class="tab active" data-view="analytics">Analytics</button>
<button class="tab" data-view="pipeline">Pipeline <span class="badge" id="pipe-badge" style="display:none"></span></button>
</div>
<div class="range" id="range-ctl">
<button data-days="7">7d</button>
<button data-days="30" class="active">30d</button>
<button data-days="90">90d</button>
</div>
</header>
<main>
<div id="view-analytics">
<div class="kpis">
<div class="kpi"><div class="num" id="k-calls">–</div><div class="lbl">Total calls</div></div>
<div class="kpi"><div class="num" id="k-leads">–</div><div class="lbl">Leads captured</div></div>
<div class="kpi"><div class="num" id="k-rate">–</div><div class="lbl">Capture rate</div></div>
<div class="kpi"><div class="num" id="k-dur">–</div><div class="lbl">Avg call length</div></div>
</div>
<div class="grid">
<div class="card"><h2>Calls per day</h2><canvas id="ch-day"></canvas></div>
<div class="card"><h2>Calls by hour (Phoenix time)</h2><canvas id="ch-hour"></canvas></div>
</div>
<div class="grid">
<div class="card"><h2>Leads by need</h2><canvas id="ch-need"></canvas></div>
<div class="card"><h2>Leads by urgency</h2><canvas id="ch-urg"></canvas></div>
</div>
<div class="card"><h2>Recent leads</h2><div id="leads-wrap"></div></div>
</div><!-- /view-analytics -->
<div id="view-pipeline" style="display:none">
<div id="stale-banner"></div>
<div class="pipe-grid" id="pipe-grid"></div>
</div>
</main>
<script>
const ORANGE = "#e8641b";
let charts = {};
let days = 30;

function fmtDur(s) {
  const m = Math.floor(s / 60), sec = s % 60;
  return m + "m " + sec + "s";
}

async function load() {
  const r = await fetch("/api/stats?days=" + days);
  const d = await r.json();

  document.getElementById("k-calls").textContent = d.total_calls;
  document.getElementById("k-leads").textContent = d.leads_captured;
  document.getElementById("k-rate").textContent = d.capture_rate + "%";
  document.getElementById("k-dur").textContent = fmtDur(d.avg_duration_sec);

  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  // calls per day
  const dayKeys = Object.keys(d.by_day).sort();
  charts.day = new Chart(document.getElementById("ch-day"), {
    type: "bar",
    data: { labels: dayKeys.map(k => k.slice(5)), datasets: [{ data: dayKeys.map(k => d.by_day[k]), backgroundColor: ORANGE, borderRadius: 4 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } }
  });

  // calls by hour
  const hours = Object.keys(d.by_hour).map(Number).sort((a, b) => a - b);
  charts.hour = new Chart(document.getElementById("ch-hour"), {
    type: "bar",
    data: { labels: hours.map(h => h + ":00"), datasets: [{ data: hours.map(h => d.by_hour[h]), backgroundColor: hours.map(h => (h < 6 || h >= 15) ? "#c0392b" : ORANGE), borderRadius: 4 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } }
  });

  // need doughnut
  const needs = Object.keys(d.need_counts);
  charts.need = new Chart(document.getElementById("ch-need"), {
    type: "doughnut",
    data: { labels: needs, datasets: [{ data: needs.map(k => d.need_counts[k]), backgroundColor: ["#e8641b", "#2e7d32", "#1565c0", "#b7791f", "#666"] }] },
    options: { plugins: { legend: { position: "bottom" } } }
  });

  // urgency doughnut
  const urg = Object.keys(d.urgency_counts);
  const urgColors = { down_now: "#c0392b", safety: "#e8641b", routine: "#2e7d32" };
  charts.urg = new Chart(document.getElementById("ch-urg"), {
    type: "doughnut",
    data: { labels: urg, datasets: [{ data: urg.map(k => d.urgency_counts[k]), backgroundColor: urg.map(k => urgColors[k] || "#666") }] },
    options: { plugins: { legend: { position: "bottom" } } }
  });

  // recent leads table
  const wrap = document.getElementById("leads-wrap");
  if (!d.recent_leads.length) {
    wrap.innerHTML = '<div class="empty">No leads captured yet in this period.<br>They will appear here after the first calls come in.</div>';
  } else {
    let html = "<table><tr><th>When</th><th>Name</th><th>Callback</th><th>Need</th><th>Urgency</th><th>Issue</th></tr>";
    for (const l of d.recent_leads) {
      html += `<tr><td>${l.started_at}</td><td>${l.name}</td><td>${l.callback}</td><td>${l.need}</td><td><span class="pill ${l.urgency}">${l.urgency}</span></td><td>${l.issue}</td></tr>`;
    }
    wrap.innerHTML = html + "</table>";
  }
}

document.querySelectorAll(".range button").forEach(b => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".range button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    days = parseInt(b.dataset.days, 10);
    load();
  });
});

// ---- view tabs ----
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    const v = t.dataset.view;
    document.getElementById("view-analytics").style.display = v === "analytics" ? "" : "none";
    document.getElementById("view-pipeline").style.display = v === "pipeline" ? "" : "none";
    document.getElementById("range-ctl").style.display = v === "analytics" ? "" : "none";
    if (v === "pipeline") loadPipeline();
  });
});

// ---- pipeline ----
const STAGE_LABELS = { new: "New", contacted: "Contacted", quoted: "Quoted", won: "Won", lost: "Lost" };
const STAGE_ORDER = ["new", "contacted", "quoted", "won", "lost"];

function esc(s) { return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

function leadCard(l) {
  const staleCls = l.hours_stale ? " stale-card" : "";
  const opts = STAGE_ORDER.map(s => `<option value="${s}"${s === l.stage ? " selected" : ""}>${STAGE_LABELS[s]}</option>`).join("");
  return `<div class="lead-card${staleCls}" data-id="${l.id}">
    <div class="nm">${esc(l.name)}</div>
    <div class="meta">${esc(l.callback)} · ${esc(l.need)} · <span class="pill ${esc(l.urgency)}">${esc(l.urgency)}</span></div>
    <div class="meta">${esc(l.started_at)}${l.company ? " · " + esc(l.company) : ""}</div>
    ${l.issue ? `<div class="meta">&ldquo;${esc(l.issue)}&rdquo;</div>` : ""}
    ${l.hours_stale ? `<div class="meta" style="color:#c0392b;font-weight:700">Stale ${l.hours_stale}h — follow up</div>` : ""}
    <select class="stage-sel">${opts}</select>
    <textarea class="note-box" placeholder="Notes…">${esc(l.notes)}</textarea>
    <button class="save-note">Save note</button>
  </div>`;
}

async function loadPipeline() {
  const r = await fetch("/api/pipeline");
  const d = await r.json();

  // badge
  const badge = document.getElementById("pipe-badge");
  if (d.open_count > 0) { badge.style.display = ""; badge.textContent = d.open_count; }
  else badge.style.display = "none";

  // stale banner
  const banner = document.getElementById("stale-banner");
  if (d.stale.length) {
    banner.innerHTML = d.stale.map(l =>
      `<div class="stale-alert"><strong>${d.stale.length} lead${d.stale.length > 1 ? "s" : ""} need${d.stale.length > 1 ? "" : "s"} follow-up:</strong> ` +
      d.stale.slice(0, 5).map(x => `${esc(x.name)} (${esc(x.callback)}, stale ${x.hours_stale}h)`).join(" · ") +
      (d.stale.length > 5 ? ` <em>and ${d.stale.length - 5} more</em>` : "") + `</div>`
    ).join("");
  } else {
    banner.innerHTML = "";
  }

  // columns
  const grid = document.getElementById("pipe-grid");
  grid.innerHTML = STAGE_ORDER.map(s =>
    `<div class="pipe-col"><h3>${STAGE_LABELS[s]}<span class="count">${d.counts[s] || 0}</span></h3>` +
    (d.stages[s] || []).map(leadCard).join("") + `</div>`
  ).join("");

  // wire stage changes
  grid.querySelectorAll(".stage-sel").forEach(sel => {
    sel.addEventListener("change", async () => {
      const id = sel.closest(".lead-card").dataset.id;
      await fetch("/api/leads/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: sel.value })
      });
      loadPipeline();
    });
  });
  // wire note saves
  grid.querySelectorAll(".save-note").forEach(btn => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".lead-card");
      const id = card.dataset.id;
      const notes = card.querySelector(".note-box").value;
      await fetch("/api/leads/" + id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes })
      });
      btn.textContent = "Saved ✓";
      setTimeout(() => btn.textContent = "Save note", 1500);
    });
  });
}

// refresh badge on load
fetch("/api/pipeline").then(r => r.json()).then(d => {
  const badge = document.getElementById("pipe-badge");
  if (d.open_count > 0) { badge.style.display = ""; badge.textContent = d.open_count; }
});

load();
</script>
</body>
</html>
"""


async def dashboard_page(authorized: bool = Depends(check_auth)):
    return HTMLResponse(DASHBOARD_HTML)


async def stats_api(request: Request, authorized: bool = Depends(check_auth)):
    try:
        days = int(request.query_params.get("days", "30"))
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    return JSONResponse(get_stats(days))


async def pipeline_api(authorized: bool = Depends(check_auth)):
    return JSONResponse(get_pipeline())


async def lead_update_api(lead_id: int, request: Request,
                         authorized: bool = Depends(check_auth)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON")
    stage = body.get("stage")
    notes = body.get("notes")
    try:
        updated = update_lead(lead_id, stage=stage, notes=notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if updated is None:
        raise HTTPException(404, "lead not found")
    return JSONResponse({"ok": True, "stage": updated["stage"]})
