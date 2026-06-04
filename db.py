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
                results   TEXT,
                origname  TEXT
            )
            """
        )
        # 구 DB 호환: 누락 컬럼 추가
        cols = [r[1] for r in conn.execute("PRAGMA table_info(checks)").fetchall()]
        if "origname" not in cols:
            conn.execute("ALTER TABLE checks ADD COLUMN origname TEXT")
        if "owner" not in cols:
            conn.execute("ALTER TABLE checks ADD COLUMN owner TEXT")
        # 사용자 계정(가입 신청 → 마스터 승인)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username  TEXT PRIMARY KEY,
                pwhash    TEXT NOT NULL,
                createdAt TEXT,
                approved  INTEGER DEFAULT 0
            )
            """
        )
        ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "approved" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN approved INTEGER DEFAULT 0")
            # 기존 사용자는 승인된 것으로 간주(승인제 도입 전 가입자)
            conn.execute("UPDATE users SET approved = 1 WHERE approved IS NULL OR approved = 0")


def get_user(username):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT username, pwhash, approved FROM users WHERE username = ?", (username,)
        ).fetchone()
    return dict(row) if row else None


def create_user(username, pwhash, approved=0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (username, pwhash, createdAt, approved) VALUES (?,?,?,?)",
            (username, pwhash, datetime.now().isoformat(timespec="seconds"), int(approved)),
        )


def list_users():
    """전체 사용자 — 승인 대기(approved=0) 먼저, 그 다음 승인됨."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT username, createdAt, approved FROM users "
            "ORDER BY approved ASC, createdAt ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def approve_user(username):
    with get_conn() as conn:
        conn.execute("UPDATE users SET approved = 1 WHERE username = ?", (username,))


def delete_user(username):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def save_check(school, sheet, counts, summary, origname, owner=None):
    """검토 1건 저장. counts는 {'PASS':n,'FAIL':n,'WARN':n,'INFO':n,'N/A':n}.
    상세 결과(results)는 보관하지 않고 원본 파일(origname)로 대체한다.
    owner는 검토를 올린 사용자명."""
    rec_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO checks
                (id, school, sheet, checkedAt, pass, fail, warn, info, na, summary, results, origname, owner)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                "[]",  # 상세 결과는 저장하지 않음
                origname,
                owner,
            ),
        )
    return rec_id


def list_checks(limit=100, owner=None):
    """owner 지정 시 해당 사용자 검토만, None이면 전체(마스터용)."""
    sql = ("SELECT id, school, sheet, checkedAt, pass, fail, warn, info, na, owner "
           "FROM checks ")
    params = []
    if owner is not None:
        sql += "WHERE owner = ? "
        params.append(owner)
    sql += "ORDER BY checkedAt DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
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
