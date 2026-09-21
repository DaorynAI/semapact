"""Shared interface parsing helpers with no domain ownership."""

from __future__ import annotations

from datetime import datetime


def parse_iso_timestamp(value: str) -> datetime:
    """Parse one timezone-aware ISO-8601 timestamp."""
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone offset")
    return parsed
