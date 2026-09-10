"""Stable serialization helpers for deterministic domain artifact identities."""

from __future__ import annotations

import json
import uuid
from typing import Any


def canonical_compact_json(payload: Any) -> str:
    """Serialize a payload using the compact canonical form used by M2 artifacts."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def deterministic_uuid5(namespace: uuid.UUID, payload: Any) -> str:
    """Return the stable UUID5 for one compact-canonical payload."""
    return str(uuid.uuid5(namespace, canonical_compact_json(payload)))
