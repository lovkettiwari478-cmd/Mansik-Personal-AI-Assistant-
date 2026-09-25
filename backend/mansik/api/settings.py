"""User settings + knowledge graph endpoints."""

from __future__ import annotations

from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..errors import NotFoundError, ValidationAppError
from ..models import AuthSession, Entity, EntityRelation, User, new_id, utcnow
from ..observability import audit
from ..security.auth import ensure_user_settings, get_db, require_auth
from .schemas import EntityIn, RelationIn, SettingsPatch

router = APIRouter(prefix="/api", tags=["settings"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


@router.get("/settings")
def get_settings_route(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = ensure_user_settings(db, user.id)
    return {
        "display_name": user.display_name,
        "email": user.email,
        "timezone": settings.timezone,
        "theme": settings.theme,
        "memory_enabled": settings.memory_enabled,
        "emergency_stop": settings.emergency_stop,
        "preferences": settings.preferences,
    }


@router.patch("/settings")
def patch_settings(
    body: SettingsPatch, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = ensure_user_settings(db, user.id)
    changed = []
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
        changed.append("display_name")
    if body.timezone is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(body.timezone)
        except Exception:
            raise ValidationAppError("Unknown timezone.")
        settings.timezone = body.timezone
        changed.append("timezone")
    if body.theme is not None:
        settings.theme = body.theme
        changed.append("theme")
    if body.memory_enabled is not None:
        settings.memory_enabled = body.memory_enabled
        changed.append("memory_enabled")
        audit(db, event_type="memory_toggled", category="memory",
              action=f"Memory {'enabled' if body.memory_enabled else 'disabled'}",
              user_id=user.id, ip=_client_ip(request), request_id=request.state.request_id)
    db.commit()
    return {"ok": True, "changed": changed}


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------

def _entity_json(e: Entity) -> dict:
    return {"id": e.id, "type": e.type, "name": e.name, "description": e.description,
            "created_at": e.created_at.isoformat()}


@router.get("/graph/entities")
def list_entities(
    type: str | None = None,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    stmt = select(Entity).where(Entity.user_id == user.id)
    if type:
        stmt = stmt.where(Entity.type == type)
    stmt = stmt.order_by(Entity.updated_at.desc()).limit(300)
    entities = db.execute(stmt).scalars().all()
    idset = {e.id for e in entities}
    rels = db.execute(
        select(EntityRelation).where(EntityRelation.user_id == user.id)
    ).scalars().all()
    return {
        "entities": [_entity_json(e) for e in entities],
        "relations": [
            {"id": r.id, "from": r.from_entity_id, "to": r.to_entity_id,
             "type": r.relation_type}
            for r in rels if r.from_entity_id in idset and r.to_entity_id in idset
        ],
    }


@router.post("/graph/entities", status_code=201)
def create_entity(
    body: EntityIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    e = Entity(
        id=new_id(), user_id=user.id, type=body.type, name=body.name.strip(),
        description=body.description, created_at=utcnow(), updated_at=utcnow(),
    )
    db.add(e)
    audit(db, event_type="entity_created", category="security",
          action=f"Graph entity created: {e.name[:100]}", user_id=user.id,
          resource=e.id, request_id=request.state.request_id)
    db.commit()
    return {"entity": _entity_json(e)}


@router.delete("/graph/entities/{entity_id}")
def delete_entity(
    entity_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    e = db.get(Entity, entity_id)
    if e is None or e.user_id != user.id:
        raise NotFoundError("Entity not found.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.post("/graph/relations", status_code=201)
def create_relation(
    body: RelationIn, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    if body.from_entity_id == body.to_entity_id:
        raise ValidationAppError("Cannot relate an entity to itself.")
    from_e = db.get(Entity, body.from_entity_id)
    to_e = db.get(Entity, body.to_entity_id)
    if from_e is None or to_e is None or from_e.user_id != user.id or to_e.user_id != user.id:
        raise NotFoundError("Entity not found.")
    r = EntityRelation(
        id=new_id(), user_id=user.id, from_entity_id=from_e.id, to_entity_id=to_e.id,
        relation_type=body.relation_type.strip(), created_at=utcnow(),
    )
    db.add(r)
    db.commit()
    return {"relation": {"id": r.id, "from": r.from_entity_id, "to": r.to_entity_id,
                         "type": r.relation_type}}
