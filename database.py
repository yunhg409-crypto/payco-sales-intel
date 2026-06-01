import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from config import DB_PATH, NEWS_CACHE_HOURS


def get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS merchants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                가맹점명 TEXT NOT NULL UNIQUE,
                업종 TEXT,
                카테고리 TEXT,
                담당자 TEXT,
                채널 TEXT,
                기존신규 TEXT
            );

            CREATE TABLE IF NOT EXISTS monthly_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                year_month TEXT NOT NULL,  -- YYYY-MM
                거래액 INTEGER DEFAULT 0,
                거래건수 INTEGER DEFAULT 0,
                프로모션여부 INTEGER DEFAULT 0,  -- 0/1
                UNIQUE(merchant_id, year_month)
            );

            CREATE TABLE IF NOT EXISTS news_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                cache_date TEXT NOT NULL,  -- YYYY-MM-DD
                summary TEXT,
                links TEXT,  -- JSON array of {title, url}
                expires_at TEXT NOT NULL,  -- ISO datetime
                UNIQUE(merchant_id, cache_date)
            );

            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                trigger_code TEXT,
                trigger_label TEXT,
                strategy_content TEXT,
                memo TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                last_contact_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_monthly_merchant ON monthly_data(merchant_id);
            CREATE INDEX IF NOT EXISTS idx_monthly_ym ON monthly_data(year_month);
            CREATE INDEX IF NOT EXISTS idx_news_merchant ON news_cache(merchant_id);
            CREATE INDEX IF NOT EXISTS idx_strategy_merchant ON strategies(merchant_id);
        """)


def upsert_merchant(conn: sqlite3.Connection, data: dict) -> int:
    conn.execute("""
        INSERT INTO merchants (가맹점명, 업종, 카테고리, 담당자, 채널, 기존신규)
        VALUES (:가맹점명, :업종, :카테고리, :담당자, :채널, :기존신규)
        ON CONFLICT(가맹점명) DO UPDATE SET
            업종=excluded.업종,
            카테고리=excluded.카테고리,
            담당자=excluded.담당자,
            채널=excluded.채널,
            기존신규=excluded.기존신규
    """, data)
    row = conn.execute("SELECT id FROM merchants WHERE 가맹점명=?", (data["가맹점명"],)).fetchone()
    return row["id"]


def upsert_monthly(conn: sqlite3.Connection, rows: list[dict]):
    conn.executemany("""
        INSERT INTO monthly_data (merchant_id, year_month, 거래액, 거래건수, 프로모션여부)
        VALUES (:merchant_id, :year_month, :거래액, :거래건수, :프로모션여부)
        ON CONFLICT(merchant_id, year_month) DO UPDATE SET
            거래액=excluded.거래액,
            거래건수=excluded.거래건수,
            프로모션여부=excluded.프로모션여부
    """, rows)


def get_merchants(manager: Optional[str] = None) -> list[dict]:
    with get_conn() as conn:
        if manager:
            rows = conn.execute(
                "SELECT * FROM merchants WHERE 담당자=? ORDER BY 가맹점명", (manager,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM merchants ORDER BY 가맹점명").fetchall()
    return [dict(r) for r in rows]


def get_managers() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT 담당자 FROM merchants WHERE 담당자 IS NOT NULL AND 담당자 != '' ORDER BY 담당자"
        ).fetchall()
    return [r["담당자"] for r in rows]


def get_monthly_data(merchant_id: int, months: int = 0) -> list[dict]:
    with get_conn() as conn:
        if months > 0:
            rows = conn.execute("""
                SELECT year_month, 거래액, 거래건수, 프로모션여부
                FROM monthly_data
                WHERE merchant_id=?
                ORDER BY year_month DESC
                LIMIT ?
            """, (merchant_id, months)).fetchall()
            return sorted([dict(r) for r in rows], key=lambda x: x["year_month"])
        else:
            rows = conn.execute("""
                SELECT year_month, 거래액, 거래건수, 프로모션여부
                FROM monthly_data
                WHERE merchant_id=?
                ORDER BY year_month
            """, (merchant_id,)).fetchall()
    return [dict(r) for r in rows]


def get_category_monthly(category: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT md.year_month, md.거래액, m.가맹점명
            FROM monthly_data md
            JOIN merchants m ON m.id = md.merchant_id
            WHERE m.카테고리=?
            ORDER BY md.year_month
        """, (category,)).fetchall()
    return [dict(r) for r in rows]


def get_news_cache(merchant_id: int) -> Optional[dict]:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT summary, links FROM news_cache
            WHERE merchant_id=? AND expires_at > ?
            ORDER BY cache_date DESC LIMIT 1
        """, (merchant_id, now)).fetchone()
    if row:
        return {"summary": row["summary"], "links": json.loads(row["links"] or "[]")}
    return None


def set_news_cache(merchant_id: int, summary: str, links: list):
    today = datetime.utcnow().date().isoformat()
    expires = (datetime.utcnow() + timedelta(hours=NEWS_CACHE_HOURS)).isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO news_cache (merchant_id, cache_date, summary, links, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(merchant_id, cache_date) DO UPDATE SET
                summary=excluded.summary, links=excluded.links, expires_at=excluded.expires_at
        """, (merchant_id, today, summary, json.dumps(links, ensure_ascii=False), expires))


def purge_expired_cache():
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("DELETE FROM news_cache WHERE expires_at <= ?", (now,))


def invalidate_news_cache(merchant_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM news_cache WHERE merchant_id=?", (merchant_id,))


# ── Strategy CRUD ──────────────────────────────────────────────

def save_strategy(merchant_id: int, trigger_code: str, trigger_label: str,
                  strategy_content: str, memo: str = "") -> int:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO strategies (merchant_id, trigger_code, trigger_label,
                                    strategy_content, memo, created_at, last_contact_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (merchant_id, trigger_code, trigger_label, strategy_content, memo, now, now))
        return cur.lastrowid


def update_strategy_memo(strategy_id: int, memo: str):
    with get_conn() as conn:
        conn.execute("UPDATE strategies SET memo=? WHERE id=?", (memo, strategy_id))


def mark_contacted(strategy_id: int):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute("UPDATE strategies SET last_contact_at=? WHERE id=?", (now, strategy_id))


def get_strategies(merchant_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM strategies WHERE merchant_id=?
            ORDER BY created_at DESC
        """, (merchant_id,)).fetchall()
    return [dict(r) for r in rows]


def get_last_contact(merchant_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT last_contact_at FROM strategies
            WHERE merchant_id=? AND last_contact_at IS NOT NULL
            ORDER BY last_contact_at DESC LIMIT 1
        """, (merchant_id,)).fetchone()
    return row["last_contact_at"] if row else None
