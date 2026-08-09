from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from open_data_contract_standard.model import OpenDataContractStandard

from semapact.lifecycle.helpers import (
    lifecycle_from_custom_properties,
    normalize_status,
    normalize_identity_name,
    build_schema_index,
    build_property_index,
)
from semapact.lifecycle.policy import BreakingChange, evaluate_merge_policy
from semapact.utils.schema_utils import contract_to_dict, contract_to_model

LOGGER = logging.getLogger(__name__)

RequiredBump = Literal["none", "minor", "major"]
ActualVersionBump = Literal["patch", "minor", "major"]

ROOT_DESCRIPTIVE_KEYS = {
    "apiVersion",
    "authoritativeDefinitions",
    "contractCreatedTs",
    "dataProduct",
    "description",
    "domain",
    "id",
    "kind",
    "name",
    "price",
    "roles",
    "slaDefaultElement",
    "slaProperties",
    "status",
    "support",
    "tags",
    "team",
    "tenant",
    "version",
}
NESTED_DESCRIPTIVE_KEYS = {
    "authoritativeDefinitions",
    "businessName",
    "classification",
    "description",
    "examples",
    "tags",
    "transformDescription",
}
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
) -> ContractChangeAssessment:
    """Classify required version bump for one contract change set.

    Rules:
    - `major`: any lifecycle policy breaking change
    - `minor`: additive, deprecation, quality, or other non-breaking structural changes
    - `none`: only descriptive metadata changes
    """
    base_model = contract_to_model(base_contract)
    candidate_model = contract_to_model(candidate_contract)

    has_changes = _canonicalize(contract_to_dict(base_model)) != _canonicalize(
        contract_to_dict(candidate_model)
    )
    if not has_changes:
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

    policy = evaluate_merge_policy(base_model, candidate_model)
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
    if _has_schema_or_property_additions(base_model, candidate_model):
        reasons.append("Schema or property additions require a minor version bump")
    if _has_new_deprecations(base_model, candidate_model):
        reasons.append("New schema/property deprecations require a minor version bump")
    if _has_non_breaking_structural_changes(base_model, candidate_model):
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


def prepare_release_candidate(
    base_contract: OpenDataContractStandard | dict[str, Any],
    candidate_contract: OpenDataContractStandard | dict[str, Any],
    release_tag: str,
) -> PromotionResult:
    """Prepare a promoted contract candidate from one governed contract.

    This function is intentionally per-contract, not per-repo.
    The release tag is supplied explicitly by the caller; core/service code
    does not read Git tags or infer repo-level release units.
    """
    base_model = contract_to_model(base_contract)
    candidate_model = contract_to_model(candidate_contract).model_copy(deep=True)

    # Root contract identity and release version stay anchored to the governed contract
    # until an explicit release tag is applied.
    candidate_model.id = base_model.id
    candidate_model.version = base_model.version

    LOGGER.info(
        "Preparing release candidate for contract %s with tag %s",
        base_model.id,
        release_tag,
    )

    assessment = classify_contract_change(base_model, candidate_model)
    if not assessment.has_changes:
        LOGGER.error("Preparation failed: contract %s has no changes", base_model.id)
        raise ValueError("Cannot promote a contract with no changes")
    if assessment.required_bump == "none":
        raise ValueError("Contract changes do not require a release version bump")

    target_version = parse_release_tag_version(release_tag)
    actual_bump = classify_version_bump(str(base_model.version or ""), target_version)
    if VERSION_RANK[actual_bump] < VERSION_RANK[assessment.required_bump]:
        raise ValueError(
            f"Release tag '{release_tag}' applies a {actual_bump} bump, but contract requires at least a "
            f"{assessment.required_bump} bump"
        )

    promoted = candidate_model.model_copy(deep=True)
    promoted.version = target_version
    return PromotionResult(
        contract=promoted,
        required_bump=assessment.required_bump,
        current_version=str(base_model.version or ""),
        target_version=target_version,
        actual_bump=actual_bump,
        release_tag=release_tag,
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


def _has_schema_or_property_additions(
    base: OpenDataContractStandard, candidate: OpenDataContractStandard
) -> bool:
    base_schema = build_schema_index(base)
    candidate_schema = build_schema_index(candidate)
    if set(candidate_schema) - set(base_schema):
        return True

    for schema_key, candidate_obj in candidate_schema.items():
        base_obj = base_schema.get(schema_key)
        if base_obj is None:
            continue
        base_props = set(build_property_index(base_obj))
        candidate_props = set(build_property_index(candidate_obj))
        if candidate_props - base_props:
            return True
    return False


def _has_new_deprecations(
    base: OpenDataContractStandard, candidate: OpenDataContractStandard
) -> bool:
    base_schema = build_schema_index(base)
    candidate_schema = build_schema_index(candidate)

    for schema_key, base_obj in base_schema.items():
        candidate_obj = candidate_schema.get(schema_key)
        if candidate_obj is None:
            continue
        if not _is_deprecated(base_obj) and _is_deprecated(candidate_obj):
            return True

        base_props = build_property_index(base_obj)
        candidate_props = build_property_index(candidate_obj)
        for prop_key, base_prop in base_props.items():
            candidate_prop = candidate_props.get(prop_key)
            if candidate_prop is None:
                continue
            if not _is_deprecated(base_prop) and _is_deprecated(candidate_prop):
                return True
    return False


def _has_non_breaking_structural_changes(
    base: OpenDataContractStandard, candidate: OpenDataContractStandard
) -> bool:
    return _canonicalize(_strip_descriptive_contract(base)) != _canonicalize(
        _strip_descriptive_contract(candidate)
    )


def _strip_descriptive_contract(contract: OpenDataContractStandard) -> dict[str, Any]:
    payload = contract_to_dict(contract)
    return _strip_descriptive_keys(payload, level=0)


def _strip_descriptive_keys(value: Any, *, level: int) -> Any:
    if isinstance(value, dict):
        ignored = ROOT_DESCRIPTIVE_KEYS if level == 0 else NESTED_DESCRIPTIVE_KEYS
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in ignored:
                continue
            cleaned[key] = _strip_descriptive_keys(item, level=level + 1)
        return cleaned
    if isinstance(value, list):
        cleaned_items = [
            _strip_descriptive_keys(item, level=level + 1) for item in value
        ]
        return _sort_identity_list(cleaned_items)
    return value


def _sort_identity_list(items: list[Any]) -> list[Any]:
    if not items:
        return items
    if all(isinstance(item, dict) and "name" in item for item in items):
        return sorted(items, key=lambda item: normalize_identity_name(item.get("name"), "Schema"))
    if all(isinstance(item, dict) and "property" in item for item in items):
        return sorted(
            items,
            key=lambda item: (
                str(item.get("property") or "").strip().lower(),
                str(item.get("value") or "").strip().lower(),
            ),
        )
    return items


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _is_deprecated(entity: Any) -> bool:
    value = getattr(entity, "lifecycleStatus", None)
    if value is None:
        value = lifecycle_from_custom_properties(
            getattr(entity, "customProperties", None)
        )
    return normalize_status(value, default="active") == "deprecated"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
