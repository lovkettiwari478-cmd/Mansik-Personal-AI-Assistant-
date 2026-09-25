"""Memory service — storage and retrieval for long-term memory.

SQLite deployments use an FTS5 full-text index (porter tokenizer) over
memories; PostgreSQL uses per-term ILIKE OR-matching (equivalent recall
for short queries). Semantic/vector search is a documented extension
point (see docs/ARCHITECTURE.md) — it is NOT faked here.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session as DbSession

from ..database import is_postgres
from ..models import Memory

_FTS_QUERY_SANITIZE = re.compile(r"[\"'*:]+")


def _terms(query: str, limit: int = 8) -> list[str]:
    cleaned = _FTS_QUERY_SANITIZE.sub(" ", query).strip()
    return [t for t in cleaned.split() if len(t) > 1][:limit]


def search_memories(db: DbSession, user_id: str, query: str, limit: int = 5) -> list[Memory]:
    """Full-text search over the user's non-deleted memories."""
    query = query.strip()
    if not query:
        return []

    terms = _terms(query)

    def _orm_like(conditions) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.deleted_at.is_(None),
                *conditions,
            )
            .order_by(Memory.importance.desc(), Memory.updated_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars())

    if is_postgres():
        # term-based OR matching (mirrors FTS5 OR semantics)
        if terms:
            conds = [Memory.content.ilike(f"%{t}%") for t in terms]
            found = _orm_like([or_(*conds)])
            if found:
                return found
        return _orm_like([Memory.content.ilike(f"%{query}%")])

    # SQLite: FTS5 first, LIKE fallback on syntax errors/misses
    if not terms:
        return _orm_like([Memory.content.like(f"%{query}%")])
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
    conds = [Memory.content.like(f"%{t}%") for t in terms]
    return _orm_like([or_(*conds)])
