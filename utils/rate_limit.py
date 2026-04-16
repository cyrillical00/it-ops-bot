"""
Per-IP daily rate limiting for Streamlit apps.
Uses a module-level dict — resets on server restart, which is acceptable
for a demo tool on Streamlit Community Cloud.
"""

from collections import defaultdict
from datetime import date

DAILY_LIMIT = 5

# { ip: [date_str, date_str, ...] }
_log: dict[str, list[str]] = defaultdict(list)


def get_client_ip() -> str:
    try:
        import streamlit as st
        headers = st.context.headers
        forwarded = headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip
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
