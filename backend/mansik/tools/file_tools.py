"""File tools — over the user's private, isolated storage."""

from __future__ import annotations

import os

from sqlalchemy import select

from ..config import RISK_HIGH_WRITE, RISK_READ, get_settings
from ..errors import NotFoundError, ValidationAppError
from ..files.service import user_file_path
from ..models import StoredFile, utcnow
from .base import Tool, ToolContext, ToolParams
from pydantic import Field


class FileListParams(ToolParams):
    limit: int = Field(50, ge=1, le=200)


class FileReadParams(ToolParams):
    file_id: str = Field(..., min_length=8, max_length=64)
    max_chars: int = Field(4000, ge=100, le=20000)


class FileDeleteParams(ToolParams):
    file_id: str = Field(..., min_length=8, max_length=64)


class FileListTool(Tool):
    id = "files.list"
    name = "List files"
    description = "List files in your private MANISK storage."
    category = "files"
    risk = RISK_READ
    params_model = FileListParams

    async def run(self, ctx: ToolContext, params: FileListParams) -> dict:
        stmt = (
            select(StoredFile)
            .where(StoredFile.user_id == ctx.user.id, StoredFile.deleted_at.is_(None))
            .order_by(StoredFile.created_at.desc())
            .limit(params.limit)
        )
        files = list(ctx.db.execute(stmt).scalars())
        return {"files": [
            {"id": f.id, "filename": f.filename, "size_bytes": f.size_bytes,
             "mime_type": f.mime_type, "created_at": f.created_at.isoformat()}
            for f in files
        ]}


class FileReadTool(Tool):
    id = "files.read_text"
    name = "Read file text"
    description = "Read the extracted text of one of your stored files."
    category = "files"
    risk = RISK_READ
    params_model = FileReadParams

    async def run(self, ctx: ToolContext, params: FileReadParams) -> dict:
        f = ctx.db.get(StoredFile, params.file_id)
        if f is None or f.user_id != ctx.user.id or f.deleted_at is not None:
            raise NotFoundError("File not found.")
        if not f.text_preview:
            return {"file_id": f.id, "filename": f.filename, "text": "", "note": "No extractable text (binary file)."}
        return {"file_id": f.id, "filename": f.filename, "text": f.text_preview[: params.max_chars]}


class FileDeleteTool(Tool):
    id = "files.delete"
    name = "Delete file"
    description = "Permanently delete one of your stored files. Requires confirmation."
    category = "files"
    risk = RISK_HIGH_WRITE  # destructive → confirmation required
    scope = "files:write"
    timeout_seconds = 10.0
    params_model = FileDeleteParams

    async def run(self, ctx: ToolContext, params: FileDeleteParams) -> dict:
        f = ctx.db.get(StoredFile, params.file_id)
        if f is None or f.user_id != ctx.user.id or f.deleted_at is not None:
            raise NotFoundError("File not found.")
        f.deleted_at = utcnow()
        try:
            path = user_file_path(f.stored_name)
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass  # DB tombstone is authoritative
        ctx.db.flush()
        return {"deleted": True, "file_id": f.id, "filename": f.filename}
