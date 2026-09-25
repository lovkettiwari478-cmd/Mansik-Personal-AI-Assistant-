"""Memory service — storage and retrieval for long-term memory.

SQLite deployments use an FTS5 full-text index (porter tokenizer) over
memories; PostgreSQL falls back to ILIKE. Semantic/vector search is a
documented extension point (see docs/ARCHITECTURE.md) — it is NOT faked
here.
"""

from __future__ import annotations

import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from ..database import is_postgres
from ..models import Memory

_FTS_QUERY_SANITIZE = re.compile(r"[\"'*:]+")


def search_memories(db: DbSession, user_id: str, query: str, limit: int = 5) -> list[Memory]:
    """Full-text search over the user's non-deleted memories."""
    query = query.strip()
    if not query:
        return []

    def _orm_like(pattern: str) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
                Memory.content.ilike(pattern) if is_postgres() else Memory.content.like(pattern),
            )
            .order_by(Memory.importance.desc(), Memory.updated_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars())

    if is_postgres():
        return _orm_like(f"%{query}%")

    # FTS5 with sanitised query; fall back to LIKE on syntax errors/misses.
    fts_query = _FTS_QUERY_SANITIZE.sub(" ", query).strip()
    terms = [t for t in fts_query.split() if len(t) > 1][:8]
    if not terms:
        return _orm_like(f"%{query}%")
    match_expr = " OR ".join(terms)
    sql = text(
        """
        SELECT m.id FROM memories m
        JOIN memories_fts f ON f.rowid = m.rowid
        WHERE memories_fts MATCH :q AND m.user_id = :uid AND m.deleted_at IS NULL
        ORDER BY bm25(memories_fts) LIMIT :lim
        """
    )
    try:
        rows = db.execute(sql, {"q": match_expr, "uid": user_id, "lim": limit}).all()
        ids = [r[0] for r in rows]
        if ids:
            stmt = (
                select(Memory)
                .where(Memory.id.in_(ids))
                .order_by(Memory.importance.desc())
                .limit(limit)
            )
            found = {m.id: m for m in db.execute(stmt).scalars()}
            return [found[i] for i in ids if i in found]
    except Exception:
        pass
    return _orm_like(f"%{query}%")
