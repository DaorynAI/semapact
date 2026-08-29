from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

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


LOGGER = logging.getLogger(__name__)

RequiredBump = Literal["none", "minor", "major"]
ActualVersionBump = Literal["patch", "minor", "major"]

SEMVER_TAG_RE = re.compile(r"(?:^|[/-])v?(?P<version>\d+\.\d+\.\d+)$")
VERSION_RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


@dataclass(slots=True)
class ContractChangeAssessment:
    """Per-contract change classification used by release workflows."""

    has_changes: bool
    required_bump: RequiredBump
    reasons: list[str] = field(default_factory=list)
    breaking_changes: list[BreakingChange] = field(default_factory=list)


@dataclass(slots=True)
class PromotionResult:
    """Prepared release candidate for a single governed contract."""

    contract: OpenDataContractStandard
    required_bump: RequiredBump
    current_version: str
    target_version: str
    actual_bump: ActualVersionBump
    release_tag: str
    reasons: list[str] = field(default_factory=list)
    breaking_changes: list[BreakingChange] = field(default_factory=list)


def classify_contract_change(
    base_contract: OpenDataContractStandard | dict[str, Any],
    candidate_contract: OpenDataContractStandard | dict[str, Any],
    *,
    changes: Sequence[GovernanceChange] | None = None,
    policy_evaluation: PolicyEvaluation | None = None,
) -> ContractChangeAssessment:
    """Classify required version bump for one contract change set.

    Rules:
    - `major`: any lifecycle policy breaking change
    - `minor`: additive, deprecation, quality, or other non-breaking structural changes
    - `none`: only descriptive metadata changes
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
        c.change_type == GovernanceChangeType.ADD
        and c.entity_type in (GovernanceEntityType.SCHEMA, GovernanceEntityType.PROPERTY)
        for c in canonical_changes
    )
    has_deprecations = any(
        c.change_type == GovernanceChangeType.DEPRECATE
        and c.entity_type in (GovernanceEntityType.SCHEMA, GovernanceEntityType.PROPERTY)
        for c in canonical_changes
    )
    has_structural = any(
        c.domain in (
            GovernanceChangeDomain.STRUCTURE,
            GovernanceChangeDomain.RELATIONSHIP,
            GovernanceChangeDomain.QUALITY,
        )
        and c.change_type != GovernanceChangeType.DEPRECATE
        for c in canonical_changes
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
            has_changes=True, required_bump="minor", reasons=_dedupe(reasons)
        )

    return ContractChangeAssessment(
        has_changes=True,
        required_bump="none",
        reasons=["Only descriptive metadata changed; no required version bump"],
    )


def apply_release_candidate(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    release_tag: str,
    *,
    required_bump: RequiredBump,
) -> PromotionResult:
    """Apply a release candidate transformation using a pre-calculated required_bump.

    Avoids duplicate policy evaluation and classification when an authoritative
    GovernanceDecision is already available.
    """
    if not isinstance(base_contract, OpenDataContractStandard):
        raise TypeError(
            f"base_contract must be OpenDataContractStandard, got {type(base_contract).__name__}"
        )
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(
            f"candidate_contract must be OpenDataContractStandard, got {type(candidate_contract).__name__}"
        )

    base_model = base_contract
    candidate_model = candidate_contract.model_copy(deep=True)

    candidate_model.id = base_model.id
    candidate_model.version = base_model.version

    LOGGER.info(
        "Applying release candidate for contract %s with tag %s (required bump: %s)",
        base_model.id,
        release_tag,
        required_bump,
    )

    if required_bump == "none":
        from semapact.exceptions import ReleaseValidationError

        raise ReleaseValidationError("Contract changes do not require a release version bump")

    target_version = parse_release_tag_version(release_tag)
    actual_bump = classify_version_bump(str(base_model.version or ""), target_version)
    if VERSION_RANK[actual_bump] < VERSION_RANK[required_bump]:
        from semapact.exceptions import ReleaseValidationError

        raise ReleaseValidationError(
            f"Release tag '{release_tag}' applies a {actual_bump} bump, but contract requires at least a "
            f"{required_bump} bump"
        )


    promoted = candidate_model.model_copy(deep=True)
    promoted.version = target_version
    return PromotionResult(
        contract=promoted,
        required_bump=required_bump,
        current_version=str(base_model.version or ""),
        target_version=target_version,
        actual_bump=actual_bump,
        release_tag=release_tag,
        reasons=[],
        breaking_changes=[],
    )


def prepare_release_candidate(
    base_contract: OpenDataContractStandard | dict[str, Any],
    candidate_contract: OpenDataContractStandard | dict[str, Any],
    release_tag: str,
) -> PromotionResult:
    """Prepare a promoted contract candidate from one governed contract.

    Maintained for backward compatibility. Runs classify_contract_change then
    delegates to apply_release_candidate.
    """
    base_model = contract_to_model(base_contract)
    candidate_model = contract_to_model(candidate_contract)

    assessment = classify_contract_change(base_model, candidate_model)
    if not assessment.has_changes:
        LOGGER.error("Preparation failed: contract %s has no changes", base_model.id)
        raise ValueError("Cannot promote a contract with no changes")

    res = apply_release_candidate(
        base_model,
        candidate_model,
        release_tag,
        required_bump=assessment.required_bump,
    )
    return PromotionResult(
        contract=res.contract,
        required_bump=res.required_bump,
        current_version=res.current_version,
        target_version=res.target_version,
        actual_bump=res.actual_bump,
        release_tag=res.release_tag,
        reasons=assessment.reasons,
        breaking_changes=assessment.breaking_changes,
    )


def parse_release_tag_version(release_tag: str) -> str:
    """Extract semantic version from an explicit per-contract release tag."""
    text = str(release_tag or "").strip()
    match = SEMVER_TAG_RE.search(text)
    if not match:
        raise ValueError(
            f"Release tag '{release_tag}' must end with a semantic version like v1.2.3"
        )
    return match.group("version")


def classify_version_bump(
    current_version: str, target_version: str
) -> ActualVersionBump:
    """Classify actual semantic version bump between current and target versions."""
    current = _parse_semver(current_version)
    target = _parse_semver(target_version)
    if target <= current:
        raise ValueError(
            f"Target version '{target_version}' must be greater than current version '{current_version}'"
        )
    if target[0] > current[0]:
        return "major"
    if target[1] > current[1]:
        return "minor"
    return "patch"


def suggest_release_version(
    current_version: str,
    required_bump: RequiredBump,
) -> str:
    """Suggest the next release version from the last released version.

    This helper always computes from the last released contract version.
    It does not chain intermediate unreleased bumps together.

    Example:
    - last released: 1.2.0
    - current unreleased delta includes both a breaking removal and an additive field
    - required bump stays `major`
    - suggested release version stays `2.0.0`, not `2.1.0`
    """
    major, minor, patch = _parse_semver(current_version)
    if required_bump == "major":
        return f"{major + 1}.0.0"
    if required_bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch}"


def _parse_semver(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(version or "").strip())
    if not match:
        raise ValueError(f"Version '{version}' must be a semantic version like 1.2.3")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
