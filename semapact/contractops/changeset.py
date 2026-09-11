"""Deterministic ChangeSet construction from authoritative governance changes."""

from __future__ import annotations

from collections.abc import Sequence

from semapact.change_context import ChangeContext
from semapact.contractops.integrity import (
    SEMAPACT_CHANGESET_NAMESPACE,
    compute_change_set_id,
)
from semapact.contractops.models import ChangeSet
from semapact.governance.models import GovernanceDecision
from semapact.lifecycle.changes import GovernanceChange, governance_change_sort_key


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
    pure: it sorts those changes canonically, derives a UUID5 from the complete stable
    proposal record, and does not inspect files, Git, clocks, or deployment state.

    Source and actor references are proposal provenance, not governance inputs. They
    therefore do not affect the upstream GovernanceDecision, but they do participate
    in ChangeSet identity so one ID always represents one immutable serialized record.
    """
    canonical_changes = tuple(sorted(tuple(changes), key=governance_change_sort_key))
    cleaned_contract_id = _required_text(contract_id, "contract_id")
    cleaned_base_ref = _required_text(base_revision_ref, "base_revision_ref")
    cleaned_candidate_ref = _required_text(
        candidate_revision_ref,
        "candidate_revision_ref",
    )
    cleaned_source = _optional_text(source)
    cleaned_actor_reference = _optional_text(actor_reference)

    change_set_id = compute_change_set_id(
        contract_id=cleaned_contract_id,
        base_revision_ref=cleaned_base_ref,
        candidate_revision_ref=cleaned_candidate_ref,
        changes=canonical_changes,
        context=context,
        source=cleaned_source,
        actor_reference=cleaned_actor_reference,
    )

    return ChangeSet(
        change_set_id=change_set_id,
        contract_id=cleaned_contract_id,
        base_revision_ref=cleaned_base_ref,
        candidate_revision_ref=cleaned_candidate_ref,
        changes=canonical_changes,
        context=context,
        source=cleaned_source,
        actor_reference=cleaned_actor_reference,
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


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional provenance values must be strings")
    cleaned = value.strip()
    return cleaned or None
