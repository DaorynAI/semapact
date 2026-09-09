from __future__ import annotations

from unittest import mock

import pytest

from semapact.contractops import ReleasePlan, VersionAuthority
from semapact.core.config import ConfigManager
from semapact.exceptions import ReleaseValidationError, ValidationError
from semapact.services import VersionAuthorityService


def _plan(required_bump: str = "minor") -> ReleasePlan:
    return ReleasePlan(
        release_plan_id="release-plan-1",
        contract_id="orders-product",
        change_set_id="change-set-1",
        decision_id="decision-1",
        release_revision_ref="rev:candidate",
        required_version_bump=required_bump,
    )


def _released_contract(sample_odcs_model):
    contract = sample_odcs_model.model_copy(deep=True)
    contract.id = "orders-product"
    contract.version = "1.2.3"
    return contract


def test_service_defaults_to_semapact_authority(sample_odcs_model) -> None:
    config = ConfigManager()
    service = VersionAuthorityService(config)
    contract = _released_contract(sample_odcs_model)

    with mock.patch.dict(
        "os.environ",
        {},
        clear=False,
    ):
        resolution = service.resolve(_plan("minor"), contract)

    assert resolution.authority is VersionAuthority.SEMAPACT
    assert resolution.selected_version == "1.3.0"


def test_service_reads_git_authority_from_config(sample_odcs_model) -> None:
    config = ConfigManager()
    config.update_config(
        {
            "release": {
                "versionAuthority": "git",
                "tagPattern": "{contractId}/v{version}",
            }
        }
    )
    service = VersionAuthorityService(config)

    resolution = service.resolve(
        _plan("minor"),
        _released_contract(sample_odcs_model),
        authority_reference="orders-product/v1.4.0",
    )

    assert resolution.authority is VersionAuthority.GIT
    assert resolution.selected_version == "1.4.0"
    assert resolution.authority_reference == "orders-product/v1.4.0"


def test_service_environment_overrides_file_authority(sample_odcs_model) -> None:
    config = ConfigManager()
    config.update_config({"release": {"versionAuthority": "semapact"}})
    service = VersionAuthorityService(config)

    with mock.patch.dict(
        "os.environ",
        {
            "SEMAPACT_RELEASE_VERSION_AUTHORITY": "git",
            "SEMAPACT_RELEASE_TAG_PATTERN": "v{version}",
        },
    ):
        resolution = service.resolve(
            _plan("major"),
            _released_contract(sample_odcs_model),
            authority_reference="v2.0.0",
        )

    assert resolution.authority is VersionAuthority.GIT
    assert resolution.selected_version == "2.0.0"


def test_service_rejects_mismatched_released_contract(sample_odcs_model) -> None:
    contract = _released_contract(sample_odcs_model)
    contract.id = "other-product"

    with pytest.raises(ReleaseValidationError, match="contract ID does not match"):
        VersionAuthorityService(ConfigManager()).resolve(_plan(), contract)


def test_service_converts_invalid_configuration_to_validation_error(
    sample_odcs_model,
) -> None:
    config = ConfigManager()
    config.update_config({"release": {"versionAuthority": "git"}})

    with pytest.raises(
        ValidationError,
        match="Invalid release version authority configuration",
    ):
        VersionAuthorityService(config).resolve(
            _plan(),
            _released_contract(sample_odcs_model),
            authority_reference="v1.3.0",
        )


def test_service_does_not_mutate_released_contract(sample_odcs_model) -> None:
    contract = _released_contract(sample_odcs_model)
    before = contract.model_dump(mode="json")

    VersionAuthorityService(ConfigManager()).resolve(_plan(), contract)

    assert contract.model_dump(mode="json") == before
