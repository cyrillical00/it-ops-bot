"""
Per-IP daily rate limiting for Streamlit apps.
Uses a module-level dict — resets on server restart, which is acceptable
for a demo tool on Streamlit Community Cloud.
"""

import os
from collections import defaultdict
from datetime import date

DAILY_LIMIT = 5

# { ip: [date_str, date_str, ...] }
_log: dict[str, list[str]] = defaultdict(list)


def _trusted_hops() -> int:
    """Number of reverse proxies in front of the app that append to X-Forwarded-For.

    Assumes Streamlit Community Cloud: one load balancer appends the address it
    saw as the right-most X-Forwarded-For entry. Anything to its left is
    client-supplied and must not be trusted. Override with TRUSTED_PROXY_HOPS.
    """
    try:
        return max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))
    except ValueError:
        return 1


def client_ip_from_headers(headers) -> str:
    """Pick the client IP from the right-most trusted hop of X-Forwarded-For."""
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    forwarded = lowered.get("x-forwarded-for", "")
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    if parts:
        hops = _trusted_hops()
        return parts[-hops] if len(parts) >= hops else parts[0]
    return "unknown"


def get_client_ip() -> str:
    try:
        import streamlit as st
        return client_ip_from_headers(st.context.headers)
    except Exception:
        pass
    return "unknown"


def remaining(ip: str) -> int:
    today = str(date.today())
    _log[ip] = [d for d in _log[ip] if d == today]
    return max(0, DAILY_LIMIT - len(_log[ip]))


def is_allowed(ip: str) -> bool:
    return remaining(ip) > 0


def record(ip: str) -> None:
    _log[ip].append(str(date.today()))
