"""Tests for src/store.py — call logging and stats."""
import os
import sys
import tempfile

# point the DB at a temp file before importing store
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
os.environ["CALL_LOG_DB"] = tmp.name

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from store import (  # noqa: E402
    classify_outcome,
    get_stats,
    log_call_end,
    log_call_start,
)
from lead import Lead  # noqa: E402


def test_full_call_cycle():
    lead = Lead(name="Mike", callback_number="(602) 555-0147",
                need_type="repair", urgency="down_now",
                equipment="Toyota forklift", issue="won't start")
    cid = log_call_start("CA123", "+16025550147")
    assert cid is not None
    assert classify_outcome(lead) == "lead_captured"
    log_call_end(cid, "lead_captured", sms_sent=True, lead=lead)

    stats = get_stats(days=30)
    assert stats["total_calls"] == 1
    assert stats["leads_captured"] == 1
    assert stats["capture_rate"] == 100.0
    assert stats["need_counts"].get("repair") == 1
    assert stats["urgency_counts"].get("down_now") == 1
    assert len(stats["recent_leads"]) == 1
    assert stats["recent_leads"][0]["name"] == "Mike"


def test_hangup_early():
    lead = Lead()
    assert classify_outcome(lead) == "hangup_early"
    cid = log_call_start("CA124", "+16025550148")
    log_call_end(cid, "hangup_early", sms_sent=False, lead=None)
    stats = get_stats(days=30)
    assert stats["total_calls"] == 2
    assert stats["hangup_early"] == 1
    assert stats["leads_captured"] == 1  # unchanged


def test_partial():
    lead = Lead(need_type="rent", issue="need a truck next week")
    assert classify_outcome(lead) == "partial"
    cid = log_call_start("CA125", "+16025550149")
    log_call_end(cid, "partial", sms_sent=False, lead=lead)
    stats = get_stats(days=30)
    assert stats["partial"] == 1
    assert stats["need_counts"].get("rent") == 1


def test_hour_buckets():
    stats = get_stats(days=30)
    assert sum(stats["by_hour"].values()) == stats["total_calls"]
    assert sum(stats["by_day"].values()) == stats["total_calls"]


if __name__ == "__main__":
    test_full_call_cycle()
    test_hangup_early()
    test_partial()
    test_hour_buckets()
    pass
    os.unlink(tmp.name)


def test_pipeline_stages():
    from store import update_lead, get_pipeline
    lead = Lead(name="Sara", callback_number="(480) 555-0199",
                need_type="buy", urgency="routine")
    cid = log_call_start("CA200", "+14805550199")
    log_call_end(cid, "lead_captured", sms_sent=True, lead=lead)

    pipe = get_pipeline()
    assert pipe["counts"]["new"] >= 1
    assert pipe["open_count"] >= 1

    # find Sara's lead id
    sara = [l for l in pipe["stages"]["new"] if l["name"] == "Sara"][0]
    updated = update_lead(sara["id"], stage="contacted")
    assert updated["stage"] == "contacted"

    updated = update_lead(sara["id"], notes="Called back, wants quote Tue")
    assert "quote" in updated["notes"]

    pipe = get_pipeline()
    assert pipe["counts"]["contacted"] >= 1

    try:
        update_lead(sara["id"], stage="bogus")
        assert False, "should have raised"
    except ValueError:
        pass


if __name__ == "__main__":
    test_full_call_cycle()
    test_hangup_early()
    test_partial()
    test_hour_buckets()
    test_pipeline_stages()
    print("store tests: 5/5 PASS")
