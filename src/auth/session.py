"""Session token helpers and role checks for API/UI auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

SESSION_COOKIE_NAME = "synthia_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "lax"
SESSION_COOKIE_SECURE = False
SESSION_TTL_SECONDS = 60 * 60 * 12


@dataclass(slots=True)
class SessionPrincipal:
    username: str
    role: str
    issued_at: int
    expires_at: int
    nonce: str


class SessionManager:
    def __init__(self, *, secret: str, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        if not secret:
            raise ValueError("session secret is required")
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = max(60, int(ttl_seconds))

    def create_token(self, *, username: str, role: str, now: int | None = None) -> str:
        if role not in {"admin", "guest"}:
            raise ValueError("role must be admin or guest")
        issued = int(time.time() if now is None else now)
        payload = {
            "u": username,
            "r": role,
            "iat": issued,
            "exp": issued + self._ttl_seconds,
            "n": secrets.token_hex(8),
        }
        encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64url_encode(self._sign(encoded_payload.encode("ascii")))
        return f"{encoded_payload}.{signature}"

    def parse_token(self, token: str, *, now: int | None = None) -> SessionPrincipal | None:
        if "." not in token:
            return None
        payload_b64, signature_b64 = token.split(".", 1)
        try:
            payload_raw = _b64url_decode(payload_b64)
            provided_signature = _b64url_decode(signature_b64)
        except Exception:
            return None
        expected_signature = self._sign(payload_b64.encode("ascii"))
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None
        try:
            payload = json.loads(payload_raw.decode("utf-8"))
        except Exception:
            return None
        username = payload.get("u")
        role = payload.get("r")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        nonce = payload.get("n")
        if (
            not isinstance(username, str)
            or role not in {"admin", "guest"}
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
            or not isinstance(nonce, str)
        ):
            return None
        now_ts = int(time.time() if now is None else now)
        if expires_at < now_ts:
            return None
        return SessionPrincipal(
            username=username,
            role=role,
            issued_at=issued_at,
            expires_at=expires_at,
            nonce=nonce,
        )

    def require_role(self, principal: SessionPrincipal | None, role: str) -> bool:
        if role not in {"admin", "guest"}:
            return False
        if principal is None:
            return False
        if role == "guest":
            return principal.role in {"guest", "admin"}
        return principal.role == "admin"

    def _sign(self, payload: bytes) -> bytes:
        return hmac.new(self._secret, payload, hashlib.sha256).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))
