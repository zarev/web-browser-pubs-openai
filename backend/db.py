import os
import time
from contextlib import contextmanager

import psycopg2
from psycopg2 import OperationalError


DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5433/publications"
DATABASE_URL = os.getenv("POSTGRES_URL", DEFAULT_DB_URL)
MAX_INIT_RETRIES = int(os.getenv("DB_INIT_RETRIES", "5"))
INIT_RETRY_DELAY = float(os.getenv("DB_INIT_RETRY_DELAY", "2.0"))


@contextmanager
def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    last_error: Exception | None = None
    for attempt in range(1, MAX_INIT_RETRIES + 1):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sources (
                            id SERIAL PRIMARY KEY,
                            url TEXT UNIQUE NOT NULL,
                            label TEXT,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS papers (
                            id SERIAL PRIMARY KEY,
                            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                            pdf_url TEXT NOT NULL,
                            title TEXT,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            UNIQUE (source_id, pdf_url)
                        );
                        """
                    )
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(INIT_RETRY_DELAY)
    if last_error:
        raise last_error


def upsert_source(conn, url: str, label: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (url, label)
            VALUES (%s, %s)
            ON CONFLICT (url) DO UPDATE SET label = COALESCE(EXCLUDED.label, sources.label)
            RETURNING id;
            """,
            (url, label),
        )
        result = cur.fetchone()
        return int(result[0])


def insert_paper(conn, source_id: int, pdf_url: str, title: str | None) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO papers (source_id, pdf_url, title)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id;
            """,
            (source_id, pdf_url, title),
        )
        return cur.fetchone() is not None


def count_papers_for_source(conn, source_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM papers WHERE source_id = %s", (source_id,))
        result = cur.fetchone()
        return int(result[0])


def fetch_sources(conn, limit: int | None = None) -> list[dict]:
    query = "SELECT id, url, label, created_at FROM sources ORDER BY id"
    params: tuple = ()
    if limit and limit > 0:
        query += " LIMIT %s"
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [
        {"id": row[0], "url": row[1], "label": row[2], "created_at": row[3]}
        for row in rows
    ]


def get_sources(limit: int | None = None) -> list[dict]:
    with get_connection() as conn:
        return fetch_sources(conn, limit)
