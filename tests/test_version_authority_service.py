from __future__ import annotations

import pytest

from semapact.contractops import ReleasePlan, VersionAuthority
from semapact.contractops.integrity import compute_release_plan_id
from semapact.core.config import ConfigManager
from semapact.exceptions import ReleaseValidationError, ValidationError
from semapact.services import VersionAuthorityService
from semapact.versioning import RequiredBump


@pytest.fixture(autouse=True)
def _clear_release_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SEMAPACT_RELEASE_VERSION_AUTHORITY",
        "SEMAPACT_RELEASE_TAG_PATTERN",
        "CONTRACTHUB_RELEASE_VERSION_AUTHORITY",
        "CONTRACTHUB_RELEASE_TAG_PATTERN",
    ):
        monkeypatch.delenv(name, raising=False)


def _config(data: dict[str, object] | None = None) -> ConfigManager:
    config = ConfigManager()
    config.config_data = {}
    if data is not None:
        config.update_config(data)
    return config


def _plan(required_bump: RequiredBump = "minor") -> ReleasePlan:
    fields = {
        "contract_id": "orders-product",
        "change_set_id": "change-set-1",
        "decision_id": "decision-1",
        "release_revision_ref": "rev:candidate",
        "required_version_bump": required_bump,
        "preconditions": (),
    }
    return ReleasePlan(
        release_plan_id=compute_release_plan_id(**fields),
        **fields,
    )


def _released_contract(sample_odcs_model):
    contract = sample_odcs_model.model_copy(deep=True)
    contract.id = "orders-product"
    contract.version = "1.2.3"
    return contract


def test_service_defaults_to_semapact_authority(sample_odcs_model) -> None:
    resolution = VersionAuthorityService(_config()).resolve(
        _plan("minor"),
        _released_contract(sample_odcs_model),
    )

    assert resolution.authority is VersionAuthority.SEMAPACT
    assert resolution.selected_version == "1.3.0"


def test_service_reads_git_authority_from_config(sample_odcs_model) -> None:
    config = _config(
        {
            "release": {
                "versionAuthority": "git",
                "tagPattern": "v{version}",
            }
        }
    )

    resolution = VersionAuthorityService(config).resolve(
        _plan("minor"),
        _released_contract(sample_odcs_model),
        authority_reference="v1.4.0",
    )

    assert resolution.authority is VersionAuthority.GIT
    assert resolution.selected_version == "1.4.0"
    assert resolution.authority_reference == "v1.4.0"


def test_service_environment_overrides_file_authority(
    sample_odcs_model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config({"release": {"versionAuthority": "semapact"}})
    monkeypatch.setenv("SEMAPACT_RELEASE_VERSION_AUTHORITY", "git")
    monkeypatch.setenv("SEMAPACT_RELEASE_TAG_PATTERN", "v{version}")

    resolution = VersionAuthorityService(config).resolve(
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
        VersionAuthorityService(_config()).resolve(_plan(), contract)


def test_service_converts_invalid_configuration_to_validation_error(
    sample_odcs_model,
) -> None:
    config = _config({"release": {"versionAuthority": "git"}})

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

    VersionAuthorityService(_config()).resolve(_plan(), contract)

    assert contract.model_dump(mode="json") == before
