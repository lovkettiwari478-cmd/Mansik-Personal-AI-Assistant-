"""Secure file storage.

- Files are stored under MANISK_STORAGE_DIR with random names (user input
  never touches the filesystem path — no traversal).
- Extension allowlist + MIME sniffing + size limit + SHA-256 on write.
- Text preview extracted for indexing/retrieval (txt/md/csv/json/yaml/html/
  log; PDF text extraction requires the optional `pypdf` package).
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets

from ..config import get_settings
from ..errors import ValidationAppError

TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".xml", ".html", ".log"}
_UNSAFE_NAME = re.compile(r"[^\w.\- ]")


def storage_root() -> str:
    settings = get_settings()
    os.makedirs(settings.storage_dir, exist_ok=True)
    return settings.storage_dir


def user_file_path(stored_name: str) -> str:
    # stored_name is server-generated ([a-f0-9]{32}); refuse anything else.
    if not re.fullmatch(r"[a-f0-9]{32}", stored_name):
        raise ValidationAppError("Invalid stored file name.")
    return os.path.join(storage_root(), stored_name)


def validate_upload(filename: str, size: int, content: bytes) -> tuple[str, str]:
    settings = get_settings()
    safe_name = _UNSAFE_NAME.sub("_", os.path.basename(filename)).strip() or "file"
    if len(safe_name) > 200:
        safe_name = safe_name[-200:]
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in settings.allowed_upload_extensions:
        raise ValidationAppError(
            f"File type '{ext or 'unknown'}' is not allowed. Allowed: {', '.join(settings.allowed_upload_extensions)}"
        )
    if size <= 0:
        raise ValidationAppError("Empty files are not allowed.")
    if size > settings.max_upload_bytes:
        raise ValidationAppError(f"File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB).")
    # sniff: reject files that claim a text-ish extension but contain
    # NUL bytes early (typical binary masquerade)
    if ext in TEXT_EXTENSIONS and b"\x00" in content[:4096]:
        raise ValidationAppError("File claims to be text but contains binary data.")
    return safe_name, ext


def extract_text(ext: str, content: bytes) -> str:
    if ext in TEXT_EXTENSIONS:
        try:
            return content.decode("utf-8", errors="replace")[:20_000]
        except Exception:
            return ""
    if ext == ".pdf":
        try:  # optional dependency
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
            return "\n".join(pages)[:20_000]
        except Exception:
            return ""
    return ""


def save_file(content: bytes) -> tuple[str, str]:
    """Writes bytes to storage; returns (stored_name, sha256)."""
    stored_name = secrets.token_hex(16)
    path = user_file_path(stored_name)
    with open(path, "wb") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    return stored_name, hashlib.sha256(content).hexdigest()


def guess_mime(filename: str, content: bytes) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    if content[:8].startswith(b"\x89PNG"):
        return "image/png"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "application/octet-stream"
