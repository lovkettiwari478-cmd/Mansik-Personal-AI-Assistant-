"""File endpoints — upload, list, download, delete (user-isolated)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..errors import NotFoundError, ValidationAppError
from ..files import service as files_service
from ..models import AuthSession, StoredFile, User, new_id, utcnow
from ..observability import audit
from ..security.auth import get_db, require_auth

router = APIRouter(prefix="/api/files", tags=["files"])


def _file_json(f: StoredFile) -> dict:
    return {
        "id": f.id, "filename": f.filename, "mime_type": f.mime_type,
        "size_bytes": f.size_bytes, "sha256": f.sha256,
        "has_text": bool(f.text_preview), "created_at": f.created_at.isoformat(),
    }


@router.get("")
def list_files(
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    rows = db.execute(
        select(StoredFile)
        .where(StoredFile.user_id == user.id, StoredFile.deleted_at.is_(None))
        .order_by(StoredFile.created_at.desc()).limit(500)
    ).scalars().all()
    total = sum(f.size_bytes for f in rows)
    return {"files": [_file_json(f) for f in rows], "count": len(rows),
            "total_bytes": total, "max_bytes": get_settings().max_upload_bytes}


@router.post("", status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    settings = get_settings()
    content = await file.read()
    filename = file.filename or "upload"
    safe_name, ext = files_service.validate_upload(filename, len(content), content)
    stored_name, sha256 = files_service.save_file(content)
    mime = files_service.guess_mime(safe_name, content)
    stored = StoredFile(
        id=new_id(), user_id=user.id, filename=safe_name, stored_name=stored_name,
        mime_type=mime, size_bytes=len(content), sha256=sha256,
        text_preview=files_service.extract_text(ext, content), created_at=utcnow(),
    )
    db.add(stored)
    audit(db, event_type="file_uploaded", category="file",
          action=f"File uploaded: {safe_name[:100]}", user_id=user.id, resource=stored.id,
          request_id=request.state.request_id, detail={"size": len(content), "mime": mime})
    db.commit()
    return {"file": _file_json(stored)}


@router.get("/{file_id}/download")
def download_file(
    file_id: str,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    f = db.get(StoredFile, file_id)
    if f is None or f.user_id != user.id or f.deleted_at is not None:
        raise NotFoundError("File not found.")
    path = files_service.user_file_path(f.stored_name)
    if not os.path.exists(path):
        raise NotFoundError("File data missing from storage.")
    return FileResponse(path, filename=f.filename, media_type=f.mime_type)


@router.delete("/{file_id}")
def delete_file(
    file_id: str, request: Request,
    auth: tuple[User, AuthSession] = Depends(require_auth),
    db: DbSession = Depends(get_db),
):
    user, _ = auth
    f = db.get(StoredFile, file_id)
    if f is None or f.user_id != user.id or f.deleted_at is not None:
        raise NotFoundError("File not found.")
    f.deleted_at = utcnow()
    try:
        path = files_service.user_file_path(f.stored_name)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    audit(db, event_type="file_deleted", category="file",
          action=f"File deleted: {f.filename[:100]}", user_id=user.id, resource=f.id,
          request_id=request.state.request_id)
    db.commit()
    return {"ok": True}
