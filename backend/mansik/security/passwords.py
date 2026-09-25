"""Password hashing with bcrypt.

bcrypt handles salt generation internally; we verify with the encoded hash.
Cost factor 12 balances security vs. latency on small instances.
"""

from __future__ import annotations

import bcrypt

ROUNDS = 12
MAX_PASSWORD_LENGTH = 256  # bcrypt truncates beyond 72 bytes; reject long pwds early
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > MAX_PASSWORD_LENGTH:
        raise ValueError("password_too_long")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw = password.encode("utf-8")
        if len(pw) > MAX_PASSWORD_LENGTH:
            return False
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_policy_error(password: str) -> str | None:
    """Returns an error message if the password violates policy, else None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        return "Password must be at most 256 characters."
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
    ])
    if classes < 2:
        return "Password must mix at least two of: lowercase, uppercase, digits."
    return None
