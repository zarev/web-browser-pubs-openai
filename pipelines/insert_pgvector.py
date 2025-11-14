"""Persist embeddings + metadata into Postgres/pgvector."""

from __future__ import annotations

from typing import Iterable

from backend.db import get_connection  # type: ignore


def insert_chunks(chunks: Iterable[dict]) -> int:
    """Stub insertion helper. Extend with pgvector usage."""
    inserted = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for chunk in chunks:
                cur.execute(
                    "INSERT INTO papers (source_id, pdf_url, title) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (chunk.get("source_id"), chunk.get("pdf_url"), chunk.get("title")),
                )
                inserted += cur.rowcount
    return inserted
