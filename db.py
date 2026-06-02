"""교육과정 검토 이력 SQLite 저장 모듈"""
import os
import json
import uuid
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checks.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id        TEXT PRIMARY KEY,
                school    TEXT,
                sheet     TEXT,
                checkedAt TEXT,
                pass      INTEGER,
                fail      INTEGER,
                warn      INTEGER,
                info      INTEGER,
                na        INTEGER,
                summary   TEXT,
                results   TEXT
            )
            """
        )


def save_check(school, sheet, counts, summary, results):
    """검토 1건 저장. counts는 {'PASS':n,'FAIL':n,'WARN':n,'INFO':n,'N/A':n}."""
    rec_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO checks
                (id, school, sheet, checkedAt, pass, fail, warn, info, na, summary, results)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rec_id,
                school,
                sheet,
                datetime.now().isoformat(timespec="seconds"),
                int(counts.get("PASS", 0)),
                int(counts.get("FAIL", 0)),
                int(counts.get("WARN", 0)),
                int(counts.get("INFO", 0)),
                int(counts.get("N/A", 0)),
                json.dumps(summary, ensure_ascii=False),
                json.dumps(results, ensure_ascii=False),
            ),
        )
    return rec_id


def list_checks(limit=100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, school, sheet, checkedAt, pass, fail, warn, info, na "
            "FROM checks ORDER BY checkedAt DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_check(rec_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM checks WHERE id = ?", (rec_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["summary"] = json.loads(d["summary"]) if d["summary"] else {}
    d["results"] = json.loads(d["results"]) if d["results"] else []
    return d


def delete_check(rec_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM checks WHERE id = ?", (rec_id,))
