"""Backend-managed JSON user authentication."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
USERS_FILE = BASE_DIR / "users.json"


def _load_users() -> list[dict[str, Any]]:
    if not USERS_FILE.exists():
        return []

    try:
        with USERS_FILE.open("r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
        users = payload.get("users", [])
        return users if isinstance(users, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _password_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()


def authenticate_user(username: str, password: str) -> dict[str, str] | None:
    normalized_username = username.strip()
    if not normalized_username or not password:
        return None

    for user in _load_users():
        stored_username = str(user.get("username", "")).strip()
        if stored_username.lower() != normalized_username.lower():
            continue

        salt = str(user.get("salt", ""))
        stored_hash = str(user.get("password_hash", ""))
        if salt and stored_hash:
            candidate_hash = _password_hash(password, salt)
            if hmac.compare_digest(candidate_hash, stored_hash):
                return {"username": stored_username, "display_name": str(user.get("display_name") or stored_username)}
            return None

        # Supports a temporary plaintext entry during local setup. Replace it
        # with password_hash and salt before deploying beyond local development.
        stored_password = str(user.get("password", ""))
        if stored_password and hmac.compare_digest(stored_password, password):
            return {"username": stored_username, "display_name": str(user.get("display_name") or stored_username)}
        return None

    return None
