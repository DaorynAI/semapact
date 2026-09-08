"""Deterministic ChangeSet construction from authoritative governance changes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

from semapact.change_context import ChangeContext
from semapact.contractops.models import ChangeSet
from semapact.governance.models import GovernanceDecision
from semapact.lifecycle.changes import GovernanceChange, governance_change_sort_key


SEMAPACT_CHANGESET_NAMESPACE = uuid.UUID("3ea0f6d8-28ca-4bb4-94f5-ea1f0f48cb84")


def build_change_set(
    *,
    contract_id: str,
    base_revision_ref: str,
    candidate_revision_ref: str,
    changes: Sequence[GovernanceChange],
    context: ChangeContext,
    source: str | None = None,
    actor_reference: str | None = None,
) -> ChangeSet:
    """Build one immutable proposal without re-diffing governed contracts.

    ``changes`` must already be authoritative M0 governance changes. Construction is
    pure: it sorts those changes canonically, derives a UUID5 from proposal-semantic
    inputs, and does not inspect files, Git, clocks, or deployment state.

    ``source`` and ``actor_reference`` are provenance only and intentionally do not
    participate in proposal identity.
    """
    canonical_changes = tuple(sorted(tuple(changes), key=governance_change_sort_key))
    cleaned_contract_id = _required_text(contract_id, "contract_id")
    cleaned_base_ref = _required_text(base_revision_ref, "base_revision_ref")
    cleaned_candidate_ref = _required_text(
        candidate_revision_ref,
        "candidate_revision_ref",
    )

    identity_payload = {
        "contract_id": cleaned_contract_id,
        "base_revision_ref": cleaned_base_ref,
        "candidate_revision_ref": cleaned_candidate_ref,
        "context": context.model_dump(mode="json"),
        "changes": [change.model_dump(mode="json") for change in canonical_changes],
    }
    canonical_payload = json.dumps(
        identity_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    change_set_id = str(uuid.uuid5(SEMAPACT_CHANGESET_NAMESPACE, canonical_payload))

    return ChangeSet(
        change_set_id=change_set_id,
        contract_id=cleaned_contract_id,
        base_revision_ref=cleaned_base_ref,
        candidate_revision_ref=cleaned_candidate_ref,
        changes=canonical_changes,
        context=context,
        source=source,
        actor_reference=actor_reference,
    )


def build_change_set_from_decision(
    decision: GovernanceDecision,
    *,
    base_revision_ref: str,
    candidate_revision_ref: str,
    source: str | None = None,
    actor_reference: str | None = None,
) -> ChangeSet:
    """Project one authoritative GovernanceDecision into its M2 proposal object."""
    return build_change_set(
        contract_id=decision.contract_id,
        base_revision_ref=base_revision_ref,
        candidate_revision_ref=candidate_revision_ref,
        changes=decision.changes,
        context=decision.context,
        source=source,
        actor_reference=actor_reference,
    )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
