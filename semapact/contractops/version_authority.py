"""Pure contract version resolution for deterministic governed releases."""

from __future__ import annotations

import json
import re
import uuid

from semapact.contractops.models import (
    ReleasePlan,
    VersionAuthority,
    VersionAuthorityConfig,
    VersionResolution,
)
from semapact.core.release import (
    ActualVersionBump,
    RequiredBump,
    classify_version_bump,
    increment_version,
    suggest_release_version,
)
from semapact.exceptions import ReleaseValidationError


SEMAPACT_VERSION_RESOLUTION_NAMESPACE = uuid.UUID(
    "4a2bd29d-2e44-44a0-9fc9-a1f4c81a2108"
)
_VERSION_TOKEN = "{version}"
_CONTRACT_ID_TOKEN = "{contractId}"


def resolve_release_version(
    release_plan: ReleasePlan,
    *,
    current_version: str,
    config: VersionAuthorityConfig,
    authority_reference: str | None = None,
) -> VersionResolution:
    """Resolve the actual release version without mutating the governed contract.

    SemaPact-managed authority selects the next deterministic version. Git-managed
    authority consumes an explicit external release reference and only validates it.
    Governance classification is never recalculated here.
    """
    if not isinstance(release_plan, ReleasePlan):
        raise TypeError(
            f"release_plan must be ReleasePlan, got {type(release_plan).__name__}"
        )
    if not isinstance(config, VersionAuthorityConfig):
        raise TypeError(
            f"config must be VersionAuthorityConfig, got {type(config).__name__}"
        )

    canonical_current = _canonical_current_version(current_version)

    if config.authority is VersionAuthority.SEMAPACT:
        if authority_reference is not None:
            raise ReleaseValidationError(
                "SemaPact version authority does not accept an external authority reference"
            )
        selected_version, actual_bump = _resolve_semapact_version(
            canonical_current,
            release_plan.required_version_bump,
        )
        normalized_reference = None
    elif config.authority is VersionAuthority.GIT:
        if authority_reference is None or not authority_reference.strip():
            raise ReleaseValidationError(
                "Git version authority requires an explicit release reference"
            )
        tag_pattern = config.tag_pattern
        if tag_pattern is None:
            raise RuntimeError(
                "VersionAuthorityConfig invariant violation: git authority requires tag_pattern"
            )
        normalized_reference = authority_reference.strip()
        selected_version = extract_version_from_release_reference(
            normalized_reference,
            tag_pattern=tag_pattern,
            contract_id=release_plan.contract_id,
        )
        try:
            actual_bump = classify_version_bump(
                canonical_current,
                selected_version,
            )
        except ValueError as exc:
            raise ReleaseValidationError(str(exc)) from exc
        _validate_minimum_bump(
            actual_bump,
            release_plan.required_version_bump,
            selected_version=selected_version,
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise RuntimeError(f"Unsupported version authority: {config.authority}")

    stable_record = {
        "release_plan_id": release_plan.release_plan_id,
        "contract_id": release_plan.contract_id,
        "release_revision_ref": release_plan.release_revision_ref,
        "authority": config.authority.value,
        "current_version": canonical_current,
        "required_version_bump": release_plan.required_version_bump,
        "selected_version": selected_version,
        "actual_bump": actual_bump,
        "authority_reference": normalized_reference,
    }
    canonical_payload = json.dumps(
        stable_record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    version_resolution_id = str(
        uuid.uuid5(SEMAPACT_VERSION_RESOLUTION_NAMESPACE, canonical_payload)
    )

    return VersionResolution(
        version_resolution_id=version_resolution_id,
        release_plan_id=release_plan.release_plan_id,
        contract_id=release_plan.contract_id,
        release_revision_ref=release_plan.release_revision_ref,
        authority=config.authority,
        current_version=canonical_current,
        required_version_bump=release_plan.required_version_bump,
        selected_version=selected_version,
        actual_bump=actual_bump,
        authority_reference=normalized_reference,
    )


def extract_version_from_release_reference(
    reference: str,
    *,
    tag_pattern: str,
    contract_id: str,
) -> str:
    """Extract a semantic version from a configured literal Git tag pattern.

    Supported placeholders are exactly ``{version}`` and optional ``{contractId}``.
    All other pattern text is treated literally rather than as a regular expression.
    """
    cleaned_reference = str(reference or "").strip()
    cleaned_pattern = str(tag_pattern or "").strip()
    cleaned_contract_id = str(contract_id or "").strip()
    if not cleaned_reference:
        raise ReleaseValidationError("Release reference must not be empty")
    if not cleaned_pattern:
        raise ReleaseValidationError("Tag pattern must not be empty")
    if not cleaned_contract_id:
        raise ReleaseValidationError("Contract ID must not be empty")

    _validate_tag_pattern(cleaned_pattern)

    regex = re.escape(cleaned_pattern)
    regex = regex.replace(
        re.escape(_VERSION_TOKEN),
        r"(?P<version>\d+\.\d+\.\d+)",
    )
    regex = regex.replace(
        re.escape(_CONTRACT_ID_TOKEN),
        re.escape(cleaned_contract_id),
    )
    match = re.fullmatch(regex, cleaned_reference)
    if match is None:
        raise ReleaseValidationError(
            f"Release reference '{cleaned_reference}' does not match tag pattern "
            f"'{cleaned_pattern}' for contract '{cleaned_contract_id}'"
        )
    return match.group("version")


def _canonical_current_version(current_version: str) -> str:
    try:
        # Existing helper returns the canonical current semantic version for a
        # required bump of ``none`` without changing legacy release behavior.
        return suggest_release_version(current_version, "none")
    except ValueError as exc:
        raise ReleaseValidationError(str(exc)) from exc


def _resolve_semapact_version(
    current_version: str,
    required_bump: RequiredBump,
) -> tuple[str, ActualVersionBump]:
    if required_bump == "major":
        actual_bump: ActualVersionBump = "major"
    elif required_bump == "minor":
        actual_bump = "minor"
    else:
        # A metadata-only governed revision still needs a distinct released ODCS
        # version when it is explicitly published. ``none`` means no minimum
        # minor/major requirement; patch is the smallest actual release bump.
        actual_bump = "patch"
    return increment_version(current_version, actual_bump), actual_bump


def _validate_minimum_bump(
    actual_bump: ActualVersionBump,
    required_bump: RequiredBump,
    *,
    selected_version: str,
) -> None:
    insufficient = (
        (required_bump == "major" and actual_bump != "major")
        or (required_bump == "minor" and actual_bump == "patch")
    )
    if insufficient:
        raise ReleaseValidationError(
            f"Resolved version '{selected_version}' applies a {actual_bump} bump, "
            f"but release requires at least a {required_bump} bump"
        )


def _validate_tag_pattern(tag_pattern: str) -> None:
    if tag_pattern.count(_VERSION_TOKEN) != 1:
        raise ReleaseValidationError(
            "Tag pattern must contain exactly one {version} placeholder"
        )
    if tag_pattern.count(_CONTRACT_ID_TOKEN) > 1:
        raise ReleaseValidationError(
            "Tag pattern may contain at most one {contractId} placeholder"
        )

    remaining = tag_pattern.replace(_VERSION_TOKEN, "").replace(_CONTRACT_ID_TOKEN, "")
    if "{" in remaining or "}" in remaining:
        raise ReleaseValidationError(
            "Tag pattern supports only {version} and {contractId} placeholders"
        )
