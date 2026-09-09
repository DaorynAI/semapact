"""Canonical governance change classification for release-version requirements."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeType,
    GovernanceEntityType,
    analyze_governance_changes,
)
from semapact.lifecycle.policy import BreakingChange, PolicyEvaluation, evaluate_merge_policy
from semapact.utils.schema_utils import contract_to_model
from semapact.versioning import RequiredBump


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ContractChangeAssessment:
    """Per-contract change classification used by governed release workflows."""

    has_changes: bool
    required_bump: RequiredBump
    reasons: list[str] = field(default_factory=list)
    breaking_changes: list[BreakingChange] = field(default_factory=list)


def classify_contract_change(
    base_contract: OpenDataContractStandard | dict[str, Any],
    candidate_contract: OpenDataContractStandard | dict[str, Any],
    *,
    changes: Sequence[GovernanceChange] | None = None,
    policy_evaluation: PolicyEvaluation | None = None,
) -> ContractChangeAssessment:
    """Classify the minimum governed release-version bump for one contract delta.

    Rules remain unchanged from the legacy release workflow:
    - ``major``: any lifecycle policy breaking change;
    - ``minor``: additive, deprecation, quality, or other non-breaking structural change;
    - ``none``: descriptive metadata-only change.
    """
    base_model = contract_to_model(base_contract)
    candidate_model = contract_to_model(candidate_contract)

    canonical_changes = (
        analyze_governance_changes(base_model, candidate_model)
        if changes is None
        else tuple(changes)
    )

    if not canonical_changes:
        return ContractChangeAssessment(
            has_changes=False,
            required_bump="none",
            reasons=["No contract changes detected"],
        )

    LOGGER.debug(
        "Classifying changes for contract %s (base version: %s)",
        base_model.id,
        base_model.version,
    )

    policy = (
        policy_evaluation
        if policy_evaluation is not None
        else evaluate_merge_policy(base_model, candidate_model, changes=canonical_changes)
    )
    if policy.breaking_changes:
        LOGGER.info(
            "Breaking changes detected in contract %s requiring major bump: %s",
            base_model.id,
            policy.breaking_changes,
        )
        return ContractChangeAssessment(
            has_changes=True,
            required_bump="major",
            reasons=["Breaking lifecycle changes require a major version bump"],
            breaking_changes=policy.breaking_changes,
        )

    reasons: list[str] = []
    has_additions = any(
        change.change_type == GovernanceChangeType.ADD
        and change.entity_type in (GovernanceEntityType.SCHEMA, GovernanceEntityType.PROPERTY)
        for change in canonical_changes
    )
    has_deprecations = any(
        change.change_type == GovernanceChangeType.DEPRECATE
        and change.entity_type in (GovernanceEntityType.SCHEMA, GovernanceEntityType.PROPERTY)
        for change in canonical_changes
    )
    has_structural = any(
        change.domain
        in (
            GovernanceChangeDomain.STRUCTURE,
            GovernanceChangeDomain.RELATIONSHIP,
            GovernanceChangeDomain.QUALITY,
        )
        and change.change_type != GovernanceChangeType.DEPRECATE
        for change in canonical_changes
    )

    if has_additions:
        reasons.append("Schema or property additions require a minor version bump")
    if has_deprecations:
        reasons.append("New schema/property deprecations require a minor version bump")
    if has_structural:
        reasons.append(
            "Non-breaking structural or quality changes require a minor version bump"
        )

    if reasons:
        return ContractChangeAssessment(
            has_changes=True,
            required_bump="minor",
            reasons=_dedupe(reasons),
        )

    return ContractChangeAssessment(
        has_changes=True,
        required_bump="none",
        reasons=["Only descriptive metadata changed; no required version bump"],
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
