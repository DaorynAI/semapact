from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True)
class AuditMetadata:
    """Audit metadata attached to lifecycle and CI artifacts."""

    last_merge_ts: str
    last_merge_actor: str
    last_merge_source: str


def build_audit_metadata(*, actor: str, source: str) -> AuditMetadata:
    """Create standard audit metadata for a merge operation."""
    ts = datetime.now(timezone.utc).isoformat()
    return AuditMetadata(
        last_merge_ts=ts, last_merge_actor=actor, last_merge_source=source
    )
