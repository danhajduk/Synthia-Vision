"""First-run setup access checks."""

from __future__ import annotations

import ipaddress
import os


def is_first_run_request_allowed(
    *,
    remote_host: str | None,
    provided_token: str | None,
) -> bool:
    if _is_localhost(remote_host):
        return True
    required_token = os.getenv("FIRST_RUN_TOKEN", "").strip()
    if not required_token:
        return False
    if not provided_token:
        return False
    return provided_token.strip() == required_token


def _is_localhost(remote_host: str | None) -> bool:
    if not remote_host:
        return False
    host = remote_host.strip()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback
