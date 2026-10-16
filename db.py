import os
import sqlite3

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.db")

COLS = ("pid", "timestamp", "memory_rss", "num_fds", "num_threads")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pid         INTEGER NOT NULL,
    timestamp   REAL    NOT NULL,
    memory_rss  INTEGER NOT NULL DEFAULT 0,
    num_fds     INTEGER NOT NULL DEFAULT 0,
    num_threads INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_snapshots_pid_ts ON snapshots (pid, timestamp);

CREATE TABLE IF NOT EXISTS incidents (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    pid       INTEGER NOT NULL,
    timestamp REAL    NOT NULL,
    severity  TEXT    NOT NULL,
    action    TEXT    NOT NULL,
    reason    TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_incidents_pid_ts ON incidents (pid, timestamp);
"""


class MonitorDB:
    def __init__(self, path=DEFAULT_DB):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def add_snapshot(self, snap):
        q = "INSERT INTO snapshots (%s) VALUES (%s)" % (
            ", ".join(COLS), ", ".join("?" * len(COLS)))
        self.conn.execute(q, [snap[c] for c in COLS])
        self.conn.commit()

    def add_incident(self, pid, ts, severity, action, reason):
        cur = self.conn.execute(
            "INSERT INTO incidents (pid, timestamp, severity, action, reason)"
            " VALUES (?,?,?,?,?)",
            (pid, ts, severity, action, reason))
        self.conn.commit()
        return cur.lastrowid

    def last_snapshots(self, pid, limit):
        rows = self.conn.execute(
            "SELECT * FROM snapshots WHERE pid=? ORDER BY timestamp DESC LIMIT ?",
            (pid, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def last_incidents(self, pid, limit=10):
        rows = self.conn.execute(
            "SELECT * FROM incidents WHERE pid=? ORDER BY timestamp DESC LIMIT ?",
            (pid, limit)).fetchall()
        return [dict(r) for r in rows]

    def stats(self, pid):
        a = self.conn.execute(
            "SELECT COUNT(*) n, MIN(timestamp) t0, MAX(timestamp) t1,"
            " MIN(memory_rss) lo, MAX(memory_rss) hi"
            " FROM snapshots WHERE pid=?", (pid,)).fetchone()
        b = self.conn.execute(
            "SELECT COUNT(*) n,"
            " SUM(CASE WHEN action='throttle' THEN 1 ELSE 0 END) throttled,"
            " SUM(CASE WHEN action='terminate' THEN 1 ELSE 0 END) killed"
            " FROM incidents WHERE pid=?", (pid,)).fetchone()
        return {
            "snapshots": a["n"] or 0,
            "first": a["t0"],
            "last": a["t1"],
            "lo": a["lo"] or 0,
            "hi": a["hi"] or 0,
            "incidents": b["n"] or 0,
            "throttled": b["throttled"] or 0,
            "killed": b["killed"] or 0,
        }

    def close(self):
        self.conn.close()
