"""Migration runner — Alembic, executed programmatically at startup.

Using real Alembic migrations (not create_all) means production upgrades
are versioned and reversible. The initial migration creates every table;
SQLite additionally gets the memories FTS5 index + triggers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from .observability import get_logger, log

logger = get_logger("mansik.migrations")

_BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"


def run_migrations() -> None:
    if not _ALEMBIC_INI.exists():
        raise RuntimeError(f"alembic.ini not found at {_ALEMBIC_INI}")
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    log(logger, "info", "migrations applied")
