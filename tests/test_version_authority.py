from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from semapact.contractops import (
    ReleasePlan,
    VersionAuthority,
    VersionAuthorityConfig,
    extract_version_from_release_reference,
    resolve_release_version,
)
from semapact.exceptions import ReleaseValidationError


def _plan(
    required_bump: str,
    *,
    contract_id: str = "orders-product",
    release_plan_id: str = "release-plan-1",
) -> ReleasePlan:
    return ReleasePlan(
        release_plan_id=release_plan_id,
        contract_id=contract_id,
        change_set_id="change-set-1",
        decision_id="decision-1",
        release_revision_ref="rev:candidate",
        required_version_bump=required_bump,
    )


@pytest.mark.parametrize(
    ("required_bump", "expected_version", "expected_actual_bump"),
    [
        ("none", "1.2.4", "patch"),
        ("minor", "1.3.0", "minor"),
        ("major", "2.0.0", "major"),
    ],
)
def test_semapact_authority_selects_smallest_valid_release_version(
    required_bump: str,
    expected_version: str,
    expected_actual_bump: str,
) -> None:
    resolution = resolve_release_version(
        _plan(required_bump),
        current_version="1.2.3",
        config=VersionAuthorityConfig(),
    )

    assert resolution.authority is VersionAuthority.SEMAPACT
    assert resolution.current_version == "1.2.3"
    assert resolution.required_version_bump == required_bump
    assert resolution.selected_version == expected_version
    assert resolution.actual_bump == expected_actual_bump
    assert resolution.authority_reference is None


def test_semapact_version_resolution_is_deterministic() -> None:
    plan = _plan("minor")
    config = VersionAuthorityConfig(authority=VersionAuthority.SEMAPACT)

    first = resolve_release_version(
        plan,
        current_version="1.2.3",
        config=config,
    )
    second = resolve_release_version(
        plan,
        current_version="1.2.3",
        config=config,
    )

    assert first == second
    assert first.version_resolution_id == second.version_resolution_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_semapact_authority_rejects_external_reference() -> None:
    with pytest.raises(
        ReleaseValidationError,
        match="does not accept an external authority reference",
    ):
        resolve_release_version(
            _plan("minor"),
            current_version="1.2.3",
            config=VersionAuthorityConfig(),
            authority_reference="v1.3.0",
        )


def test_git_authority_uses_exact_external_version_without_selecting_another() -> None:
    resolution = resolve_release_version(
        _plan("minor"),
        current_version="1.2.3",
        config=VersionAuthorityConfig(
            authority=VersionAuthority.GIT,
            tag_pattern="v{version}",
        ),
        authority_reference="v1.4.0",
    )

    assert resolution.authority is VersionAuthority.GIT
    assert resolution.selected_version == "1.4.0"
    assert resolution.actual_bump == "minor"
    assert resolution.authority_reference == "v1.4.0"


def test_git_authority_supports_contract_scoped_tag_pattern() -> None:
    resolution = resolve_release_version(
        _plan("major"),
        current_version="1.2.3",
        config=VersionAuthorityConfig(
            authority=VersionAuthority.GIT,
            tag_pattern="{contractId}/v{version}",
        ),
        authority_reference="orders-product/v2.1.0",
    )

    assert resolution.selected_version == "2.1.0"
    assert resolution.actual_bump == "major"


def test_git_authority_rejects_insufficient_bump() -> None:
    with pytest.raises(ReleaseValidationError, match="requires at least a major bump"):
        resolve_release_version(
            _plan("major"),
            current_version="1.2.3",
            config=VersionAuthorityConfig(
                authority=VersionAuthority.GIT,
                tag_pattern="v{version}",
            ),
            authority_reference="v1.3.0",
        )


def test_git_authority_accepts_any_positive_bump_when_governance_requires_none() -> None:
    resolution = resolve_release_version(
        _plan("none"),
        current_version="1.2.3",
        config=VersionAuthorityConfig(
            authority=VersionAuthority.GIT,
            tag_pattern="v{version}",
        ),
        authority_reference="v2.0.0",
    )

    assert resolution.selected_version == "2.0.0"
    assert resolution.actual_bump == "major"


def test_git_authority_requires_version_greater_than_current() -> None:
    with pytest.raises(ReleaseValidationError, match="must be greater than current"):
        resolve_release_version(
            _plan("none"),
            current_version="1.2.3",
            config=VersionAuthorityConfig(
                authority=VersionAuthority.GIT,
                tag_pattern="v{version}",
            ),
            authority_reference="v1.2.3",
        )


def test_git_authority_requires_explicit_release_reference() -> None:
    with pytest.raises(
        ReleaseValidationError,
        match="requires an explicit release reference",
    ):
        resolve_release_version(
            _plan("minor"),
            current_version="1.2.3",
            config=VersionAuthorityConfig(
                authority=VersionAuthority.GIT,
                tag_pattern="v{version}",
            ),
        )


def test_release_reference_pattern_is_literal_and_contract_scoped() -> None:
    assert (
        extract_version_from_release_reference(
            "orders.product/v1.2.3",
            tag_pattern="{contractId}/v{version}",
            contract_id="orders.product",
        )
        == "1.2.3"
    )

    with pytest.raises(ReleaseValidationError, match="does not match tag pattern"):
        extract_version_from_release_reference(
            "ordersXproduct/v1.2.3",
            tag_pattern="{contractId}/v{version}",
            contract_id="orders.product",
        )


def test_release_reference_rejects_unknown_pattern_placeholders() -> None:
    with pytest.raises(ReleaseValidationError, match="supports only"):
        extract_version_from_release_reference(
            "main/v1.2.3",
            tag_pattern="{repo}/v{version}",
            contract_id="orders-product",
        )


def test_version_authority_config_fails_closed_on_incompatible_fields() -> None:
    with pytest.raises(PydanticValidationError, match="requires tag_pattern"):
        VersionAuthorityConfig(authority=VersionAuthority.GIT)

    with pytest.raises(PydanticValidationError, match="only valid for git"):
        VersionAuthorityConfig(
            authority=VersionAuthority.SEMAPACT,
            tag_pattern="v{version}",
        )


def test_version_resolution_rejects_invalid_current_version() -> None:
    with pytest.raises(ReleaseValidationError, match="must be a semantic version"):
        resolve_release_version(
            _plan("minor"),
            current_version="latest",
            config=VersionAuthorityConfig(),
        )


def test_version_resolution_identity_changes_with_authoritative_inputs() -> None:
    plan = _plan("minor")
    config = VersionAuthorityConfig(
        authority=VersionAuthority.GIT,
        tag_pattern="v{version}",
    )

    first = resolve_release_version(
        plan,
        current_version="1.2.3",
        config=config,
        authority_reference="v1.3.0",
    )
    second = resolve_release_version(
        plan,
        current_version="1.2.3",
        config=config,
        authority_reference="v1.4.0",
    )

    assert first.version_resolution_id != second.version_resolution_id


def test_version_resolution_is_immutable() -> None:
    resolution = resolve_release_version(
        _plan("minor"),
        current_version="1.2.3",
        config=VersionAuthorityConfig(),
    )

    with pytest.raises(PydanticValidationError):
        resolution.selected_version = "9.9.9"  # type: ignore[misc]
