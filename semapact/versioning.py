"""Canonical semantic-version primitives shared by governance and ContractOps."""

from __future__ import annotations

import re
from typing import Literal

RequiredBump = Literal["none", "minor", "major"]
ActualVersionBump = Literal["patch", "minor", "major"]

_VERSION_RANK: dict[str, int] = {
    "none": 0,
    "patch": 1,
    "minor": 2,
    "major": 3,
}


def normalize_semver(version: str) -> str:
    """Validate and return canonical ``major.minor.patch`` form."""
    major, minor, patch = _parse_semver(version)
    return f"{major}.{minor}.{patch}"


def classify_version_bump(
    current_version: str,
    target_version: str,
) -> ActualVersionBump:
    """Classify the actual positive semantic-version bump."""
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


def increment_version(
    current_version: str,
    bump: ActualVersionBump,
) -> str:
    """Return the next semantic version for an explicit actual release bump."""
    major, minor, patch = _parse_semver(current_version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unsupported version bump: {bump}")


def version_bump_satisfies(
    actual_bump: ActualVersionBump,
    required_bump: RequiredBump,
) -> bool:
    """Return whether an actual release bump satisfies a governance minimum."""
    return _VERSION_RANK[actual_bump] >= _VERSION_RANK[required_bump]


def suggest_release_version(
    current_version: str,
    required_bump: RequiredBump,
) -> str:
    """Suggest the next version from one last released contract version.

    ``none`` preserves legacy suggestion semantics and returns the normalized current
    version. ContractOps may independently choose a patch when an explicit governed
    release still requires a distinct version.
    """
    if required_bump == "major":
        return increment_version(current_version, "major")
    if required_bump == "minor":
        return increment_version(current_version, "minor")
    return normalize_semver(current_version)


def _parse_semver(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(version or "").strip())
    if not match:
        raise ValueError(f"Version '{version}' must be a semantic version like 1.2.3")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
