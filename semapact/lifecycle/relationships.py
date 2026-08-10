"""Relationship endpoint normalization helpers for SemaPact lifecycle governance."""
from __future__ import annotations

from typing import Any


def normalize_relationship_endpoint(val: Any) -> str:
    """Normalize a single relationship endpoint string.

    Splits on ``'.'``, strips each part, lowercases, and rejoins.  This
    ensures that ``"  Orders.user_id "`` and ``"orders.user_id"`` resolve to
    the same canonical string.
    """
    if val is None:
        return ""
    parts = [p.strip().lower() for p in str(val).split(".")]
    return ".".join(parts)


def normalize_endpoint_value(val: Any) -> str:
    """Normalize a relationship endpoint value (scalar or list).

    When *val* is a list (combined/multi-column key), each element is
    normalized individually in original order and joined with a comma.
    Order is preserved because composite FK column positions encode column
    mappings (e.g. ``[a, b] -> [x, y]`` differs from ``[a, b] -> [y, x]``).
    """
    if isinstance(val, list):
        return ",".join(normalize_relationship_endpoint(item) for item in val)
    return normalize_relationship_endpoint(val)
