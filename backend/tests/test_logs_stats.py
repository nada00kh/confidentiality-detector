import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import main
from backend.app.storage import REASON_CLEAN, REASON_MASKED, AuditLog, masking_text
from backend.tests.conftest import SECRET, FakeDetector, assert_error

# 09:00 in Riyadh (UTC+3).
NOW = datetime(2026, 10, 21, 6, 0, tzinfo=timezone.utc)

LOG_ITEM_KEYS = {"operation_id", "time", "detected", "decision", "reason", "masking"}
STATS_KEYS = {"days", "total", "allowed", "blocked", "daily", "top_types", "latest"}


@pytest.fixture
def audit_log(settings):
    return AuditLog(settings.db_path, settings.timezone)


@pytest.fixture
def client(make_client, monkeypatch):
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    return make_client(detector=FakeDetector())


def record(audit_log, when, counts=None):
    """Save a scan the way /api/check does: BLOCK when anything was detected, ALLOW otherwise."""
    counts = counts or {}
    masked = sum(counts.values())
    decision, reason = ("BLOCK", REASON_MASKED) if masked else ("ALLOW", REASON_CLEAN)
    return audit_log.record(decision, reason, masking_text(masked), counts, when)


def test_masking_text():
    assert masking_text(0) == "No changes"
    assert masking_text(1) == "1 item masked"
    assert masking_text(2) == "2 items masked"


# ---------- /api/logs ----------

def test_logs_response_matches_the_contract(client, audit_log):
    record(audit_log, NOW - timedelta(minutes=5), {"PERSON_NAME": 1, "NATIONAL_ID": 1})
    record(audit_log, NOW - timedelta(minutes=4))
    body = client.get("/api/logs").json()
    assert set(body) == {"total", "page", "page_size", "items"}
    assert (body["total"], body["page"], body["page_size"]) == (2, 1, 10)
    assert all(set(item) == LOG_ITEM_KEYS for item in body["items"])
    assert body["items"] == [
        {
            "operation_id": "WSQ-000002",
            "time": "2026-10-21T05:56:00Z",
            "detected": [],
            "decision": "ALLOW",
            "reason": "No sensitive data found",
            "masking": "No changes",
        },
        {
            "operation_id": "WSQ-000001",
            "time": "2026-10-21T05:55:00Z",
            "detected": [
                {"type": "PERSON_NAME", "label": "Person name", "count": 1},
                {"type": "NATIONAL_ID", "label": "National ID", "count": 1},
            ],
            "decision": "BLOCK",
            "reason": "Sensitive data found, masked copy returned",
            "masking": "2 items masked",
        },
    ]


def test_logs_are_newest_first_and_paginated(client, audit_log):
    for minute in range(25):
        record(audit_log, NOW - timedelta(minutes=30 - minute))
    page1 = client.get("/api/logs?page=1&page_size=10").json()
    page3 = client.get("/api/logs?page=3&page_size=10").json()
    assert page1["total"] == 25
    assert [i["operation_id"] for i in page1["items"]][:2] == ["WSQ-000025", "WSQ-000024"]
    assert len(page3["items"]) == 5 and page3["items"][-1]["operation_id"] == "WSQ-000001"
    assert client.get("/api/logs?page=9").json()["items"] == []


def test_logs_filter_by_decision(client, audit_log):
    record(audit_log, NOW, {"EMAIL": 1})  # WSQ-000001 BLOCK
    record(audit_log, NOW)  # WSQ-000002 ALLOW
    record(audit_log, NOW, {"PASSWORD": 2})  # WSQ-000003 BLOCK
    record(audit_log, NOW)  # WSQ-000004 ALLOW

    blocked = client.get("/api/logs?decision=BLOCK").json()
    allowed = client.get("/api/logs?decision=ALLOW").json()
    assert blocked["total"] == 2 and [i["operation_id"] for i in blocked["items"]] == ["WSQ-000003", "WSQ-000001"]
    assert allowed["total"] == 2 and [i["operation_id"] for i in allowed["items"]] == ["WSQ-000004", "WSQ-000002"]
    assert all(i["decision"] == "BLOCK" and i["detected"] for i in blocked["items"])
    assert all(i["decision"] == "ALLOW" and not i["detected"] for i in allowed["items"])


def test_logs_other_filters(client, audit_log):
    record(audit_log, NOW, {"EMAIL": 1})
    record(audit_log, NOW, {"PASSWORD": 2})
    record(audit_log, NOW)
    record(audit_log, NOW)

    def ids(query):
        return [i["operation_id"] for i in client.get("/api/logs" + query).json()["items"]]

    assert ids("?type=PASSWORD") == ["WSQ-000002"]
    assert ids("?decision=BLOCK&type=EMAIL") == ["WSQ-000001"]
    assert ids("?decision=ALLOW&type=EMAIL") == []
    assert ids("?q=wsq-000004") == ["WSQ-000004"]
    assert ids("?q=00000") == ["WSQ-000004", "WSQ-000003", "WSQ-000002", "WSQ-000001"]
    assert ids("?q=%25") == [] and ids("?q=_") == []  # LIKE wildcards are matched literally
    assert ids("?q=") == ids("")  # an empty search is ignored, as the frontend expects


def test_logs_days_window_uses_local_days(client, audit_log):
    record(audit_log, datetime(2026, 10, 20, 21, 30, tzinfo=timezone.utc))  # 00:30 on Oct 21 in Riyadh
    record(audit_log, datetime(2026, 10, 20, 20, 30, tzinfo=timezone.utc))  # 23:30 on Oct 20 in Riyadh
    record(audit_log, NOW - timedelta(days=40))
    assert client.get("/api/logs?days=1").json()["total"] == 1
    assert client.get("/api/logs?days=2").json()["total"] == 2
    assert client.get("/api/logs?days=90").json()["total"] == 3


def test_logs_page_size_is_capped(client):
    assert_error(client.get("/api/logs?page_size=101"), 422)
    assert client.get("/api/logs?page_size=100").status_code == 200


@pytest.mark.parametrize(
    "query",
    ["decision=MAYBE", "decision=allow", "type=NOT_A_TYPE", "days=0", "days=91", "days=abc",
     "page=0", "page_size=0", "page_size=101", "q=" + "W" * 21],
)
def test_logs_invalid_parameters(client, query):
    detail = assert_error(client.get("/api/logs?" + query), 422)
    assert "MAYBE" not in detail and "NOT_A_TYPE" not in detail and "WWW" not in detail


# ---------- /api/stats ----------

def test_stats_response_matches_the_contract(client, audit_log):
    record(audit_log, NOW, {"PERSON_NAME": 3})
    record(audit_log, NOW - timedelta(days=1), {"PERSON_NAME": 1, "EMAIL": 1})
    record(audit_log, NOW - timedelta(days=2))
    body = client.get("/api/stats?days=7").json()

    assert set(body) == STATS_KEYS
    assert (body["days"], body["total"], body["allowed"], body["blocked"]) == (7, 3, 1, 2)
    assert [d["date"] for d in body["daily"]] == [f"2026-10-{day}" for day in range(15, 22)]
    assert body["daily"][-1] == {"date": "2026-10-21", "allow": 0, "block": 1}
    assert body["daily"][-2] == {"date": "2026-10-20", "allow": 0, "block": 1}
    assert body["daily"][-3] == {"date": "2026-10-19", "allow": 1, "block": 0}
    assert body["top_types"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 4},
        {"type": "EMAIL", "label": "Email address", "count": 1},
    ]
    assert [i["operation_id"] for i in body["latest"]] == ["WSQ-000003", "WSQ-000002", "WSQ-000001"]
    assert all(set(i) == LOG_ITEM_KEYS for i in body["latest"])


@pytest.mark.parametrize("days", [1, 7, 30])
def test_stats_totals_add_up(client, audit_log, days):
    for offset in range(40):
        record(audit_log, NOW - timedelta(hours=11 * offset), {"EMAIL": 1} if offset % 3 else None)
    body = client.get(f"/api/stats?days={days}").json()
    assert body["allowed"] + body["blocked"] == body["total"]
    assert sum(d["allow"] for d in body["daily"]) == body["allowed"]
    assert sum(d["block"] for d in body["daily"]) == body["blocked"]
    assert len(body["daily"]) == days
    assert body["total"] == client.get(f"/api/logs?days={days}").json()["total"]
    assert body["blocked"] == client.get(f"/api/logs?days={days}&decision=BLOCK").json()["total"]


def test_stats_with_no_data(client):
    body = client.get("/api/stats?days=30").json()
    assert set(body) == STATS_KEYS
    assert (body["total"], body["allowed"], body["blocked"]) == (0, 0, 0)
    assert len(body["daily"]) == 30 and body["top_types"] == [] and body["latest"] == []


def test_stats_groups_days_in_the_company_time_zone(client, audit_log):
    record(audit_log, datetime(2026, 10, 20, 21, 30, tzinfo=timezone.utc))  # Oct 21 in Riyadh
    daily = client.get("/api/stats?days=2").json()["daily"]
    assert daily == [{"date": "2026-10-20", "allow": 0, "block": 0}, {"date": "2026-10-21", "allow": 1, "block": 0}]


def test_stats_limits_top_types_and_latest_to_six(client, audit_log):
    codes = ["PERSON_NAME", "NATIONAL_ID", "PHONE", "EMAIL", "IBAN", "CARD_NUMBER", "PASSWORD", "USERNAME"]
    for n, code in enumerate(codes, start=1):
        record(audit_log, NOW, {code: n})
    body = client.get("/api/stats").json()
    assert [t["type"] for t in body["top_types"]] == codes[::-1][:6]
    assert len(body["latest"]) == 6


@pytest.mark.parametrize("query", ["days=0", "days=91", "days=week"])
def test_stats_invalid_days(client, query):
    assert_error(client.get("/api/stats?" + query), 422)


# ---------- scans feed the logs, and nothing sensitive is stored ----------

def test_scans_appear_in_logs_and_stats(make_client, monkeypatch):
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    client = make_client(detector=FakeDetector(("Ahmed", "FIRSTNAME"), (SECRET, "CREDITCARDNUMBER")))
    client.post("/api/check", json={"text": f"Ahmed paid with {SECRET}"})
    client.post("/api/check", json={"text": "Nothing to see"})

    items = client.get("/api/logs").json()["items"]
    assert [(i["operation_id"], i["decision"], i["reason"], i["masking"]) for i in items] == [
        ("WSQ-000002", "ALLOW", "No sensitive data found", "No changes"),
        ("WSQ-000001", "BLOCK", "Sensitive data found, masked copy returned", "2 items masked"),
    ]
    assert items[1]["detected"] == [
        {"type": "PERSON_NAME", "label": "Person name", "count": 1},
        {"type": "CARD_NUMBER", "label": "Card number", "count": 1},
    ]
    stats = client.get("/api/stats").json()
    assert (stats["total"], stats["allowed"], stats["blocked"]) == (2, 1, 1)


def test_database_never_contains_scanned_text(make_client, settings):
    client = make_client(detector=FakeDetector(("Ahmed", "FIRSTNAME"), (SECRET, "CREDITCARDNUMBER")))
    text = f"Ahmed paid with {SECRET} for order UNIQUEWORD"
    result = client.post("/api/check", json={"text": text}).json()
    clean = client.post("/api/check", json={"text": "plain text UNMASKEDWORD"}).json()
    assert (result["decision"], clean["decision"]) == ("BLOCK", "ALLOW")

    raw = b"".join(p.read_bytes() for p in settings.db_path.parent.glob("washq.sqlite3*"))
    for value in (SECRET, "Ahmed", "UNIQUEWORD", "UNMASKEDWORD", result["safe_text"], clean["safe_text"]):
        assert value.encode() not in raw

    with sqlite3.connect(settings.db_path) as conn:
        columns = {
            table: [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
    assert columns == {
        "operations": ["id", "created_at", "decision", "reason", "masking"],
        "operation_types": ["operation_id", "position", "type", "count"],
    }


def test_audit_log_survives_a_restart(make_client):
    make_client(detector=FakeDetector()).post("/api/check", json={"text": "hello"})
    second = make_client(detector=FakeDetector())
    assert second.get("/api/logs").json()["total"] == 1
    assert second.post("/api/check", json={"text": "hi"}).json()["operation_id"] == "WSQ-000002"


# ---------- migration of rows saved before ALLOW/BLOCK changed meaning ----------

def write_old_rows(path):
    """Rows as the previous version saved them: scans with detections were ALLOW."""
    from backend.app.storage import SCHEMA

    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO operations (created_at, decision, reason, masking) VALUES (?, ?, ?, ?)",
            [
                ("2026-10-20T08:00:00Z", "ALLOW", "Allowed after masking", "2 items masked"),
                ("2026-10-20T09:00:00Z", "ALLOW", "No sensitive data found", "No changes"),
                ("2026-10-20T10:00:00Z", "ALLOW", "Allowed after masking", "1 item masked"),
            ],
        )
        conn.executemany(
            "INSERT INTO operation_types (operation_id, position, type, count) VALUES (?, ?, ?, ?)",
            [(1, 0, "PERSON_NAME", 1), (1, 1, "NATIONAL_ID", 1), (3, 0, "EMAIL", 1)],
        )


def test_old_allow_rows_with_detections_become_block(settings):
    write_old_rows(settings.db_path)
    items = AuditLog(settings.db_path, settings.timezone).logs(NOW, days=30)["items"]
    assert [(i["operation_id"], i["decision"], i["reason"], i["masking"]) for i in items] == [
        ("WSQ-000003", "BLOCK", REASON_MASKED, "1 item masked"),
        ("WSQ-000002", "ALLOW", REASON_CLEAN, "No changes"),
        ("WSQ-000001", "BLOCK", REASON_MASKED, "2 items masked"),
    ]
    # Detected types and times are kept as they were.
    assert [d["type"] for d in items[2]["detected"]] == ["PERSON_NAME", "NATIONAL_ID"]
    assert items[2]["time"] == "2026-10-20T08:00:00Z"


def test_migration_is_safe_to_run_again(settings):
    write_old_rows(settings.db_path)
    first = AuditLog(settings.db_path, settings.timezone).logs(NOW, days=30)
    second = AuditLog(settings.db_path, settings.timezone).logs(NOW, days=30)
    assert first == second
