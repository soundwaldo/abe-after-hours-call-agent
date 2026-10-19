"""store.py — SQLite call + lead logging for the analytics dashboard.

No external dependencies. The database file lives at CALL_LOG_DB
(default ./data/calls.db). Every call gets a row; every captured lead
gets linked to its call.
"""
import os
import sqlite3
import threading
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    PHX = ZoneInfo("America/Phoenix")
except Exception:  # pragma: no cover
    PHX = None

DB_PATH = os.getenv("CALL_LOG_DB", os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "calls.db"))

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT UNIQUE,
    caller_number TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT DEFAULT '',
    duration_sec INTEGER DEFAULT 0,
    outcome TEXT DEFAULT 'unknown',
    sms_sent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL REFERENCES calls(id),
    name TEXT DEFAULT '',
    callback_number TEXT DEFAULT '',
    number_confirmed INTEGER DEFAULT 0,
    company TEXT DEFAULT '',
    need_type TEXT DEFAULT '',
    equipment TEXT DEFAULT '',
    issue TEXT DEFAULT '',
    urgency TEXT DEFAULT '',
    service_location TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_leads_call ON leads(call_id);
"""

PIPELINE_SCHEMA = """
ALTER TABLE leads ADD COLUMN stage TEXT DEFAULT 'new';
ALTER TABLE leads ADD COLUMN stage_updated_at TEXT DEFAULT '';
"""

STAGES = ("new", "contacted", "quoted", "won", "lost")

# hours before a stage counts as stale (needs follow-up)
STALE_HOURS = {"new": 24, "contacted": 72, "quoted": 72}


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)
        # lightweight migration for the pipeline columns
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(leads)")}
        if "stage" not in cols:
            conn.executescript(PIPELINE_SCHEMA)


def _now_iso():
    if PHX:
        return datetime.now(PHX).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


def log_call_start(call_sid, caller_number=""):
    """Record an inbound call. Returns the call row id."""
    init_db()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO calls (call_sid, caller_number, started_at)"
            " VALUES (?, ?, ?)",
            (call_sid, caller_number, _now_iso()))
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM calls WHERE call_sid = ?",
            (call_sid,)).fetchone()
        return row["id"] if row else None


def log_call_end(call_id, outcome, sms_sent=False, lead=None):
    """Close out a call. outcome: lead_captured | partial | hangup_early."""
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE calls SET ended_at = ?, outcome = ?, sms_sent = ?"
            " WHERE id = ?",
            (_now_iso(), outcome, 1 if sms_sent else 0, call_id))
        # duration from started_at
        row = conn.execute(
            "SELECT started_at FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row and row["started_at"]:
            try:
                start = datetime.fromisoformat(row["started_at"])
                now = datetime.now(PHX) if PHX else datetime.now()
                if start.tzinfo is None and now.tzinfo is not None:
                    start = start.replace(tzinfo=now.tzinfo)
                secs = max(0, int((now - start).total_seconds()))
                conn.execute(
                    "UPDATE calls SET duration_sec = ? WHERE id = ?",
                    (secs, call_id))
            except Exception:
                pass
        if lead is not None:
            conn.execute(
                """INSERT INTO leads
                   (call_id, name, callback_number, number_confirmed, company,
                    need_type, equipment, issue, urgency, service_location, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (call_id, lead.name, lead.callback_number,
                 1 if lead.number_confirmed else 0, lead.company,
                 lead.need_type, lead.equipment, lead.issue,
                 lead.urgency, lead.service_location, lead.notes))
        conn.commit()


def classify_outcome(lead):
    if lead.name.strip() or lead.callback_number.strip():
        return "lead_captured"
    if lead.issue.strip() or lead.need_type.strip():
        return "partial"
    return "hangup_early"


def update_lead(lead_id, stage=None, notes=None):
    """Move a lead through the pipeline and/or update notes."""
    init_db()
    if stage is not None and stage not in STAGES:
        raise ValueError(f"bad stage: {stage}")
    with _lock, _connect() as conn:
        if stage is not None:
            conn.execute(
                "UPDATE leads SET stage = ?, stage_updated_at = ? WHERE id = ?",
                (stage, _now_iso(), lead_id))
        if notes is not None:
            conn.execute(
                "UPDATE leads SET notes = ? WHERE id = ?", (notes, lead_id))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def get_pipeline():
    """Leads grouped by stage, plus the stale list needing follow-up."""
    init_db()
    now = datetime.now(PHX) if PHX else datetime.now()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT l.*, c.started_at, c.caller_number
               FROM leads l JOIN calls c ON c.id = l.call_id
               ORDER BY c.started_at DESC""").fetchall()

    stages = {s: [] for s in STAGES}
    stale = []
    for r in rows:
        lead = {
            "id": r["id"],
            "started_at": (r["started_at"] or "")[:16].replace("T", " "),
            "name": r["name"] or "-",
            "callback": r["callback_number"] or "-",
            "need": r["need_type"] or "-",
            "urgency": r["urgency"] or "-",
            "issue": (r["issue"] or "")[:80],
            "notes": r["notes"] or "",
            "stage": r["stage"] or "new",
            "company": r["company"] or "",
        }
        stages.setdefault(lead["stage"], stages["new"]).append(lead)
        # stale check
        limit = STALE_HOURS.get(lead["stage"])
        if limit and lead["stage"] not in ("won", "lost"):
            anchor = r["stage_updated_at"] or r["started_at"]
            try:
                then = datetime.fromisoformat(anchor)
                if then.tzinfo is None and now.tzinfo is not None:
                    then = then.replace(tzinfo=now.tzinfo)
                hours_old = (now - then).total_seconds() / 3600
                if hours_old > limit:
                    lead["hours_stale"] = int(hours_old)
                    stale.append(lead)
            except (ValueError, TypeError):
                pass

    stale.sort(key=lambda l: l.get("hours_stale", 0), reverse=True)
    counts = {s: len(v) for s, v in stages.items()}
    open_count = counts["new"] + counts["contacted"] + counts["quoted"]
    return {"stages": stages, "counts": counts,
            "open_count": open_count, "stale": stale[:20]}


def get_stats(days=30):
    """Aggregate stats for the dashboard."""
    init_db()
    since = ((datetime.now(PHX) if PHX else datetime.now())
             - timedelta(days=days)).isoformat()
    with _lock, _connect() as conn:
        calls = conn.execute(
            "SELECT * FROM calls WHERE started_at >= ? ORDER BY started_at DESC",
            (since,)).fetchall()

    total = len(calls)
    captured = sum(1 for c in calls if c["outcome"] == "lead_captured")
    partial = sum(1 for c in calls if c["outcome"] == "partial")
    hung = sum(1 for c in calls if c["outcome"] == "hangup_early")

    # calls per day
    by_day = {}
    for c in calls:
        day = c["started_at"][:10]
        by_day[day] = by_day.get(day, 0) + 1

    # calls per hour (0-23 Phoenix time)
    by_hour = {h: 0 for h in range(24)}
    for c in calls:
        try:
            h = int(c["started_at"][11:13])
            by_hour[h] += 1
        except (ValueError, IndexError):
            pass

    # avg duration of completed calls
    durations = [c["duration_sec"] for c in calls if c["duration_sec"] > 0]
    avg_dur = int(sum(durations) / len(durations)) if durations else 0

    with _lock, _connect() as conn:
        leads = conn.execute(
            """SELECT l.*, c.started_at, c.caller_number, c.duration_sec
               FROM leads l JOIN calls c ON c.id = l.call_id
               WHERE c.started_at >= ? ORDER BY c.started_at DESC""",
            (since,)).fetchall()

    need_counts, urgency_counts = {}, {}
    for lead in leads:
        nt = lead["need_type"] or "other"
        need_counts[nt] = need_counts.get(nt, 0) + 1
        u = lead["urgency"] or "routine"
        urgency_counts[u] = urgency_counts.get(u, 0) + 1

    recent = []
    for lead in leads[:20]:
        recent.append({
            "started_at": lead["started_at"][:16].replace("T", " "),
            "name": lead["name"] or "-",
            "callback": lead["callback_number"] or "-",
            "need": lead["need_type"] or "-",
            "urgency": lead["urgency"] or "-",
            "issue": (lead["issue"] or "")[:60],
            "duration": lead["duration_sec"],
        })

    return {
        "days": days,
        "total_calls": total,
        "leads_captured": captured,
        "partial": partial,
        "hangup_early": hung,
        "capture_rate": round(100 * captured / total, 1) if total else 0,
        "avg_duration_sec": avg_dur,
        "by_day": by_day,
        "by_hour": by_hour,
        "need_counts": need_counts,
        "urgency_counts": urgency_counts,
        "recent_leads": recent,
    }
