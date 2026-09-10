from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.lifecycle.change_classification import (
    ContractChangeAssessment,
    classify_contract_change,
)
from semapact.lifecycle.policy import BreakingChange
from semapact.utils.schema_utils import contract_to_model
from semapact.versioning import (
    ActualVersionBump,
    RequiredBump,
    classify_version_bump,
    increment_version,
    normalize_semver,
    suggest_release_version,
    version_bump_satisfies,
)


LOGGER = logging.getLogger(__name__)

SEMVER_TAG_RE = re.compile(r"(?:^|[/-])v?(?P<version>\d+\.\d+\.\d+)$")


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


def apply_release_candidate(
    base_contract: OpenDataContractStandard,
    candidate_contract: OpenDataContractStandard,
    release_tag: str,
    *,
    required_bump: RequiredBump,
) -> PromotionResult:
    """Apply a legacy release candidate using a pre-calculated required bump.

    This compatibility workflow preserves its historical semantics. Canonical M2
    ContractOps release execution lives outside this module.
    """
    if not isinstance(base_contract, OpenDataContractStandard):
        raise TypeError(
            f"base_contract must be OpenDataContractStandard, got {type(base_contract).__name__}"
        )
    if not isinstance(candidate_contract, OpenDataContractStandard):
        raise TypeError(
            "candidate_contract must be OpenDataContractStandard, "
            f"got {type(candidate_contract).__name__}"
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
    if not version_bump_satisfies(actual_bump, required_bump):
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
    """Prepare a promoted contract candidate through the legacy compatibility path."""
    base_model = contract_to_model(base_contract)
    candidate_model = contract_to_model(candidate_contract)

    assessment = classify_contract_change(base_model, candidate_model)
    if not assessment.has_changes:
        LOGGER.error("Preparation failed: contract %s has no changes", base_model.id)
        raise ValueError("Cannot promote a contract with no changes")

    result = apply_release_candidate(
        base_model,
        candidate_model,
        release_tag,
        required_bump=assessment.required_bump,
    )
    return PromotionResult(
        contract=result.contract,
        required_bump=result.required_bump,
        current_version=result.current_version,
        target_version=result.target_version,
        actual_bump=result.actual_bump,
        release_tag=result.release_tag,
        reasons=assessment.reasons,
        breaking_changes=assessment.breaking_changes,
    )


def parse_release_tag_version(release_tag: str) -> str:
    """Extract semantic version from an explicit legacy release tag."""
    text = str(release_tag or "").strip()
    match = SEMVER_TAG_RE.search(text)
    if not match:
        raise ValueError(
            f"Release tag '{release_tag}' must end with a semantic version like v1.2.3"
        )
    return match.group("version")


__all__ = [
    "ActualVersionBump",
    "ContractChangeAssessment",
    "PromotionResult",
    "RequiredBump",
    "apply_release_candidate",
    "classify_contract_change",
    "classify_version_bump",
    "increment_version",
    "normalize_semver",
    "parse_release_tag_version",
    "prepare_release_candidate",
    "suggest_release_version",
]
