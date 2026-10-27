"""SQLite audit log behind the dashboard and the security logs.

Only operation metadata is stored: time, decision, reason, masking result and the
detected type codes with their counts. The scanned text, the safe text and the
detected values are never written here.
"""

import sqlite3
import threading
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.labels import TYPE_LABELS

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,  -- UTC, e.g. 2026-10-21T07:42:00Z
    decision TEXT NOT NULL CHECK (decision IN ('ALLOW', 'BLOCK')),
    reason TEXT NOT NULL,
    masking TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operations_created_at ON operations (created_at);
CREATE TABLE IF NOT EXISTS operation_types (
    operation_id INTEGER NOT NULL REFERENCES operations (id),
    position INTEGER NOT NULL,  -- order in which the types first appeared
    type TEXT NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0),
    PRIMARY KEY (operation_id, type)
);
"""

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
LATEST_LIMIT = 6
TOP_TYPES_LIMIT = 6

# Reasons and masking results saved with each scan.
REASON_CLEAN = "No sensitive data found"
REASON_MASKED = "Sensitive data found, masked copy returned"
REASON_NOT_MASKED = "Sensitive data found, but a masked copy could not be made"
MASKING_NOT_MASKED = "Not masked"

# Before ALLOW/BLOCK changed meaning, scans with detections were saved as ALLOW.
# BLOCK now means "sensitive data found", so those rows become BLOCK. Safe to run repeatedly.
MIGRATIONS = f"""
UPDATE operations SET decision = 'BLOCK', reason = '{REASON_MASKED}'
WHERE decision = 'ALLOW'
  AND EXISTS (SELECT 1 FROM operation_types t WHERE t.operation_id = operations.id);
"""


class StorageError(Exception):
    """The audit log could not be read or written."""


def format_operation_id(row_id: int) -> str:
    return f"WSQ-{row_id:06d}"


def masking_text(masked_count: int) -> str:
    if not masked_count:
        return "No changes"
    return f"{masked_count} {'item' if masked_count == 1 else 'items'} masked"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AuditLog:
    def __init__(self, path: Path, timezone_name: str):
        self.path = Path(path)
        self.tz = ZoneInfo(timezone_name)
        self._ready = False
        self._lock = threading.Lock()

    # ---------- connection ----------

    def _connect(self) -> sqlite3.Connection:
        # The file and tables are created on first use, so importing the app creates nothing.
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.path) as conn:
                    conn.executescript(SCHEMA + MIGRATIONS)
                self._ready = True
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, work):
        try:
            conn = self._connect()
            try:
                with conn:  # commits on success, rolls back on error
                    return work(conn)
            finally:
                conn.close()
        except sqlite3.Error:
            raise StorageError from None

    # ---------- time windows ----------

    def _window(self, days: int, now: datetime) -> tuple[list[date], str]:
        """The last `days` local calendar days (oldest first) and the UTC start of the first one."""
        today = now.astimezone(self.tz).date()
        dates = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
        start = datetime.combine(dates[0], time.min, tzinfo=self.tz).astimezone(timezone.utc)
        return dates, start.strftime(TIME_FORMAT)

    def _local_date(self, created_at: str) -> date:
        moment = datetime.strptime(created_at, TIME_FORMAT).replace(tzinfo=timezone.utc)
        return moment.astimezone(self.tz).date()

    # ---------- writing ----------

    def record(self, decision: str, reason: str, masking: str, counts: dict[str, int], now: datetime) -> str:
        created_at = now.astimezone(timezone.utc).strftime(TIME_FORMAT)

        def work(conn):
            cursor = conn.execute(
                "INSERT INTO operations (created_at, decision, reason, masking) VALUES (?, ?, ?, ?)",
                (created_at, decision, reason, masking),
            )
            row_id = cursor.lastrowid
            conn.executemany(
                "INSERT INTO operation_types (operation_id, position, type, count) VALUES (?, ?, ?, ?)",
                [(row_id, position, code, count) for position, (code, count) in enumerate(counts.items())],
            )
            return format_operation_id(row_id)

        return self._run(work)

    # ---------- reading ----------

    @staticmethod
    def _items(conn, rows) -> list[dict]:
        ids = [row["id"] for row in rows]
        detected: dict[int, list[dict]] = {row_id: [] for row_id in ids}
        if ids:
            placeholders = ",".join("?" * len(ids))
            for t in conn.execute(
                f"SELECT operation_id, type, count FROM operation_types "
                f"WHERE operation_id IN ({placeholders}) ORDER BY operation_id, position",
                ids,
            ):
                detected[t["operation_id"]].append(
                    {"type": t["type"], "label": TYPE_LABELS.get(t["type"], t["type"]), "count": t["count"]}
                )
        return [
            {
                "operation_id": format_operation_id(row["id"]),
                "time": row["created_at"],
                "detected": detected[row["id"]],
                "decision": row["decision"],
                "reason": row["reason"],
                "masking": row["masking"],
            }
            for row in rows
        ]

    def logs(
        self,
        now: datetime,
        days: int = 7,
        decision: str | None = None,
        type_code: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        _, since = self._window(days, now)
        where = ["o.created_at >= ?"]
        params: list = [since]
        if decision:
            where.append("o.decision = ?")
            params.append(decision)
        if type_code:
            where.append("EXISTS (SELECT 1 FROM operation_types t WHERE t.operation_id = o.id AND t.type = ?)")
            params.append(type_code)
        if q:
            where.append("('WSQ-' || printf('%06d', o.id)) LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q.upper())}%")
        condition = " AND ".join(where)

        def work(conn):
            total = conn.execute(f"SELECT COUNT(*) FROM operations o WHERE {condition}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT o.* FROM operations o WHERE {condition} ORDER BY o.id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            return {"total": total, "page": page, "page_size": page_size, "items": self._items(conn, rows)}

        return self._run(work)

    def stats(self, now: datetime, days: int = 7) -> dict:
        dates, since = self._window(days, now)

        def work(conn):
            rows = conn.execute(
                "SELECT created_at, decision FROM operations WHERE created_at >= ?", (since,)
            ).fetchall()
            daily = {d: Counter() for d in dates}
            for row in rows:
                day = self._local_date(row["created_at"])
                if day in daily:
                    daily[day][row["decision"]] += 1

            types = conn.execute(
                "SELECT t.type, SUM(t.count) AS total FROM operation_types t "
                "JOIN operations o ON o.id = t.operation_id WHERE o.created_at >= ? "
                "GROUP BY t.type ORDER BY total DESC, t.type LIMIT ?",
                (since, TOP_TYPES_LIMIT),
            ).fetchall()
            latest = conn.execute(
                "SELECT * FROM operations WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
                (since, LATEST_LIMIT),
            ).fetchall()

            allowed = sum(c["ALLOW"] for c in daily.values())
            blocked = sum(c["BLOCK"] for c in daily.values())
            return {
                "days": days,
                "total": allowed + blocked,
                "allowed": allowed,
                "blocked": blocked,
                "daily": [{"date": d.isoformat(), "allow": c["ALLOW"], "block": c["BLOCK"]} for d, c in daily.items()],
                "top_types": [
                    {"type": t["type"], "label": TYPE_LABELS.get(t["type"], t["type"]), "count": t["total"]}
                    for t in types
                ],
                "latest": self._items(conn, latest),
            }

        return self._run(work)
