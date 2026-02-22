"""Password hashing and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Callable

_ARGON2_PREFIX = "$argon2"
_SCRYPT_PREFIX = "scrypt"
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64

_argon2_hash: Callable[[str], str] | None = None
_argon2_verify: Callable[[str, str], bool] | None = None

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ph = PasswordHasher()

    def _argon2_hash_impl(password: str) -> str:
        return _ph.hash(password)

    def _argon2_verify_impl(encoded: str, password: str) -> bool:
        try:
            return bool(_ph.verify(encoded, password))
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    _argon2_hash = _argon2_hash_impl
    _argon2_verify = _argon2_verify_impl
except Exception:
    _argon2_hash = None
    _argon2_verify = None


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be a string with at least 8 characters")
    if _argon2_hash is not None:
        return _argon2_hash(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return (
        f"{_SCRYPT_PREFIX}${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith(_ARGON2_PREFIX) and _argon2_verify is not None:
        return _argon2_verify(encoded, password)
    try:
        algo, n_s, r_s, p_s, salt_hex, digest_hex = encoded.split("$", 5)
        if algo != _SCRYPT_PREFIX:
            return False
        n = int(n_s)
        r = int(r_s)
        p = int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except Exception:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)
