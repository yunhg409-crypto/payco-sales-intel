"""
database.py — SQLite (로컬) / PostgreSQL (배포) 자동 전환
DATABASE_URL 환경변수가 있으면 PostgreSQL 사용, 없으면 SQLite 사용
"""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from config import DB_PATH, NEWS_CACHE_HOURS

DATABASE_URL = os.getenv("DATABASE_URL", "")
IS_POSTGRES = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")


# ── 커넥션 ─────────────────────────────────────────────────────

def get_conn():
    if IS_POSTGRES:
        import psycopg2, psycopg2.extras
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url, options="-c statement_timeout=0 -c lock_timeout=0")
        conn.autocommit = False
        return conn
    else:
        import sqlite3
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _rows(cursor) -> list[dict]:
    """커서 결과 → dict 리스트 (SQLite·PG 공통)"""
    if IS_POSTGRES:
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        return [dict(r) for r in cursor.fetchall()]


def _one(cursor) -> Optional[dict]:
    if IS_POSTGRES:
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    else:
        row = cursor.fetchone()
        return dict(row) if row else None


def _ph(n: int = 1) -> str:
    """플레이스홀더: SQLite=? / PG=%s"""
    return "%s" if IS_POSTGRES else "?"


def _phs(n: int) -> str:
    ph = _ph()
    return ", ".join([ph] * n)


# ── 스키마 초기화 ───────────────────────────────────────────────

def init_db():
    conn = get_conn()
    try:
        cur = conn.cursor()
        if IS_POSTGRES:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    industry TEXT, category TEXT, manager TEXT,
                    channel TEXT, merchant_type TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS monthly_data (
                    id SERIAL PRIMARY KEY,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    year_month TEXT NOT NULL,
                    amount BIGINT DEFAULT 0,
                    count INTEGER DEFAULT 0,
                    has_promo INTEGER DEFAULT 0,
                    UNIQUE(merchant_id, year_month)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS news_cache (
                    id SERIAL PRIMARY KEY,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    cache_date TEXT NOT NULL,
                    summary TEXT, links TEXT, expires_at TEXT NOT NULL,
                    UNIQUE(merchant_id, cache_date)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id SERIAL PRIMARY KEY,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    trigger_code TEXT, trigger_label TEXT,
                    strategy_content TEXT, memo TEXT DEFAULT '',
                    created_at TEXT NOT NULL, last_contact_at TEXT
                )
            """)
        else:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS merchants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    industry TEXT, category TEXT, manager TEXT,
                    channel TEXT, merchant_type TEXT
                );
                CREATE TABLE IF NOT EXISTS monthly_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    year_month TEXT NOT NULL,
                    amount INTEGER DEFAULT 0,
                    count INTEGER DEFAULT 0,
                    has_promo INTEGER DEFAULT 0,
                    UNIQUE(merchant_id, year_month)
                );
                CREATE TABLE IF NOT EXISTS news_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    cache_date TEXT NOT NULL,
                    summary TEXT, links TEXT, expires_at TEXT NOT NULL,
                    UNIQUE(merchant_id, cache_date)
                );
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    trigger_code TEXT, trigger_label TEXT,
                    strategy_content TEXT, memo TEXT DEFAULT '',
                    created_at TEXT NOT NULL, last_contact_at TEXT
                );
            """)
        conn.commit()
    finally:
        conn.close()


# ── 가맹점 CRUD ─────────────────────────────────────────────────

def upsert_merchant(conn, data: dict) -> int:
    ph = _ph()
    cur = conn.cursor()
    if IS_POSTGRES:
        cur.execute(f"""
            INSERT INTO merchants (name, industry, category, manager, channel, merchant_type)
            VALUES ({_phs(6)})
            ON CONFLICT(name) DO UPDATE SET
                industry=EXCLUDED.industry, category=EXCLUDED.category,
                manager=EXCLUDED.manager, channel=EXCLUDED.channel,
                merchant_type=EXCLUDED.merchant_type
            RETURNING id
        """, (data["가맹점명"], data["업종"], data["카테고리"], data["담당자"], data["채널"], data["기존신규"]))
        return cur.fetchone()[0]
    else:
        conn.execute(f"""
            INSERT INTO merchants (name, industry, category, manager, channel, merchant_type)
            VALUES ({_phs(6)})
            ON CONFLICT(name) DO UPDATE SET
                industry=excluded.industry, category=excluded.category,
                manager=excluded.manager, channel=excluded.channel,
                merchant_type=excluded.merchant_type
        """, (data["가맹점명"], data["업종"], data["카테고리"], data["담당자"], data["채널"], data["기존신규"]))
        row = conn.execute(f"SELECT id FROM merchants WHERE name={ph}", (data["가맹점명"],)).fetchone()
        return row["id"]


def upsert_monthly(conn, rows: list[dict]):
    if not rows:
        return
    values = [(r["merchant_id"], r["year_month"], r["거래액"], r["거래건수"], r["프로모션여부"]) for r in rows]
    if IS_POSTGRES:
        cur = conn.cursor()
        cur.executemany(f"""
            INSERT INTO monthly_data (merchant_id, year_month, amount, count, has_promo)
            VALUES ({_phs(5)})
            ON CONFLICT(merchant_id, year_month) DO UPDATE SET
                amount=EXCLUDED.amount, count=EXCLUDED.count, has_promo=EXCLUDED.has_promo
        """, values)
    else:
        conn.executemany(f"""
            INSERT INTO monthly_data (merchant_id, year_month, amount, count, has_promo)
            VALUES ({_phs(5)})
            ON CONFLICT(merchant_id, year_month) DO UPDATE SET
                amount=excluded.amount, count=excluded.count, has_promo=excluded.has_promo
        """, values)


def get_merchants(manager: Optional[str] = None) -> list[dict]:
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        if manager:
            cur.execute(f"SELECT * FROM merchants WHERE manager={ph} ORDER BY name", (manager,))
        else:
            cur.execute("SELECT * FROM merchants ORDER BY name")
        rows = _rows(cur)
    finally:
        conn.close()
    return [_normalize_merchant(r) for r in rows]


def get_managers() -> list[str]:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT manager FROM merchants WHERE manager IS NOT NULL AND manager != '' ORDER BY manager")
        rows = _rows(cur)
    finally:
        conn.close()
    return [r["manager"] for r in rows]


def get_monthly_data(merchant_id: int, months: int = 0) -> list[dict]:
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        if months > 0:
            cur.execute(f"""
                SELECT year_month, amount, count, has_promo
                FROM monthly_data WHERE merchant_id={ph}
                ORDER BY year_month DESC LIMIT {ph}
            """, (merchant_id, months))
            rows = sorted(_rows(cur), key=lambda x: x["year_month"])
        else:
            cur.execute(f"""
                SELECT year_month, amount, count, has_promo
                FROM monthly_data WHERE merchant_id={ph}
                ORDER BY year_month
            """, (merchant_id,))
            rows = _rows(cur)
    finally:
        conn.close()
    return [_normalize_monthly(r) for r in rows]


def get_all_data() -> tuple[list[dict], list[dict]]:
    """가맹점 + 전체 월별 데이터를 단일 커넥션으로 2번 쿼리 반환."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM merchants ORDER BY name")
        merchants = [_normalize_merchant(r) for r in _rows(cur)]
        cur.execute("SELECT * FROM monthly_data ORDER BY merchant_id, year_month")
        monthly_rows = [_normalize_monthly(r) | {"merchant_id": r["merchant_id"]} for r in _rows(cur)]
    finally:
        conn.close()
    return merchants, monthly_rows


def get_all_data_joined() -> list[dict]:
    """가맹점 + 월별 데이터를 JOIN 단일 쿼리로 반환. 네트워크 왕복 1번."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                m.id, m.name, m.industry, m.category, m.manager, m.channel, m.merchant_type,
                md.year_month, md.amount, md.count, md.has_promo
            FROM merchants m
            LEFT JOIN monthly_data md ON md.merchant_id = m.id
            ORDER BY m.id, md.year_month
        """)
        rows = _rows(cur)
    finally:
        conn.close()
    return rows


def get_category_monthly(category: str) -> list[dict]:
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT md.year_month, md.amount, m.name as 가맹점명
            FROM monthly_data md JOIN merchants m ON m.id=md.merchant_id
            WHERE m.category={ph} ORDER BY md.year_month
        """, (category,))
        rows = _rows(cur)
    finally:
        conn.close()
    return [{"year_month": r["year_month"], "거래액": r["amount"], "가맹점명": r["가맹점명"]} for r in rows]


# ── 뉴스 캐시 ──────────────────────────────────────────────────

def get_news_cache(merchant_id: int) -> Optional[dict]:
    ph = _ph()
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT summary, links FROM news_cache
            WHERE merchant_id={ph} AND expires_at>{ph}
            ORDER BY cache_date DESC LIMIT 1
        """, (merchant_id, now))
        row = _one(cur)
    finally:
        conn.close()
    if row:
        return {"summary": row["summary"], "links": json.loads(row["links"] or "[]")}
    return None


def set_news_cache(merchant_id: int, summary: str, links: list):
    today = datetime.utcnow().date().isoformat()
    expires = (datetime.utcnow() + timedelta(hours=NEWS_CACHE_HOURS)).isoformat()
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            INSERT INTO news_cache (merchant_id, cache_date, summary, links, expires_at)
            VALUES ({_phs(5)})
            ON CONFLICT(merchant_id, cache_date) DO UPDATE SET
                summary=EXCLUDED.summary, links=EXCLUDED.links, expires_at=EXCLUDED.expires_at
        """, (merchant_id, today, summary, json.dumps(links, ensure_ascii=False), expires))
        conn.commit()
    finally:
        conn.close()


def purge_expired_cache():
    ph = _ph()
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM news_cache WHERE expires_at<={ph}", (now,))
        conn.commit()
    finally:
        conn.close()


def invalidate_news_cache(merchant_id: int):
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM news_cache WHERE merchant_id={ph}", (merchant_id,))
        conn.commit()
    finally:
        conn.close()


# ── 전략 CRUD ──────────────────────────────────────────────────

def save_strategy(merchant_id: int, trigger_code: str, trigger_label: str,
                  strategy_content: str, memo: str = "") -> int:
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    try:
        cur = conn.cursor()
        if IS_POSTGRES:
            cur.execute(f"""
                INSERT INTO strategies (merchant_id,trigger_code,trigger_label,strategy_content,memo,created_at,last_contact_at)
                VALUES ({_phs(7)}) RETURNING id
            """, (merchant_id, trigger_code, trigger_label, strategy_content, memo, now, now))
            rid = cur.fetchone()[0]
        else:
            cur.execute(f"""
                INSERT INTO strategies (merchant_id,trigger_code,trigger_label,strategy_content,memo,created_at,last_contact_at)
                VALUES ({_phs(7)})
            """, (merchant_id, trigger_code, trigger_label, strategy_content, memo, now, now))
            rid = cur.lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()


def update_strategy_memo(strategy_id: int, memo: str):
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE strategies SET memo={ph} WHERE id={ph}", (memo, strategy_id))
        conn.commit()
    finally:
        conn.close()


def mark_contacted(strategy_id: int):
    ph = _ph()
    now = datetime.utcnow().isoformat()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE strategies SET last_contact_at={ph} WHERE id={ph}", (now, strategy_id))
        conn.commit()
    finally:
        conn.close()


def get_strategies(merchant_id: int) -> list[dict]:
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM strategies WHERE merchant_id={ph} ORDER BY created_at DESC", (merchant_id,))
        rows = _rows(cur)
    finally:
        conn.close()
    return rows


def get_last_contact(merchant_id: int) -> Optional[str]:
    ph = _ph()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT last_contact_at FROM strategies
            WHERE merchant_id={ph} AND last_contact_at IS NOT NULL
            ORDER BY last_contact_at DESC LIMIT 1
        """, (merchant_id,))
        row = _one(cur)
    finally:
        conn.close()
    return row["last_contact_at"] if row else None


# ── 정규화 헬퍼 (컬럼명 통일) ───────────────────────────────────

def _normalize_merchant(r: dict) -> dict:
    return {
        "id": r["id"],
        "가맹점명": r.get("name", ""),
        "업종": r.get("industry") or "",
        "카테고리": r.get("category") or "",
        "담당자": r.get("manager") or "",
        "채널": r.get("channel") or "",
        "기존신규": r.get("merchant_type") or "",
    }


def _normalize_monthly(r: dict) -> dict:
    return {
        "year_month": r["year_month"],
        "거래액": r.get("amount", 0) or 0,
        "거래건수": r.get("count", 0) or 0,
        "프로모션여부": r.get("has_promo", 0) or 0,
    }
