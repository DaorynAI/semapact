"""Application boundary for configured contract version authority."""

from __future__ import annotations

from open_data_contract_standard.model import OpenDataContractStandard
from pydantic import ValidationError as PydanticValidationError

from semapact.contractops import (
    ReleasePlan,
    VersionAuthority,
    VersionAuthorityConfig,
    VersionResolution,
    resolve_release_version,
)
from semapact.core.config import ConfigManager
from semapact.exceptions import ReleaseValidationError, ValidationError


class VersionAuthorityService:
    """Resolve a ReleasePlan using application configuration and released ODCS state."""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self._config = config_manager or ConfigManager()

    def resolve(
        self,
        release_plan: ReleasePlan,
        released_contract: OpenDataContractStandard,
        *,
        authority_reference: str | None = None,
    ) -> VersionResolution:
        """Resolve the actual release version without mutating the contract."""
        if not isinstance(release_plan, ReleasePlan):
            raise TypeError(
                f"release_plan must be ReleasePlan, got {type(release_plan).__name__}"
            )
        if not isinstance(released_contract, OpenDataContractStandard):
            raise TypeError(
                "released_contract must be OpenDataContractStandard, "
                f"got {type(released_contract).__name__}"
            )

        contract_id = str(released_contract.id or "").strip()
        if contract_id != release_plan.contract_id:
            raise ReleaseValidationError(
                "Released contract ID does not match ReleasePlan contract ID"
            )

        current_version = str(released_contract.version or "").strip()
        if not current_version:
            raise ReleaseValidationError(
                "Released contract must define the current ODCS version"
            )

        return resolve_release_version(
            release_plan,
            current_version=current_version,
            config=self.load_config(),
            authority_reference=authority_reference,
        )

    def load_config(self) -> VersionAuthorityConfig:
        """Resolve typed version-authority config from standard SemaPact config sources."""
        authority = self._config.get(
            "release.versionAuthority",
            env_var="SEMAPACT_RELEASE_VERSION_AUTHORITY",
            default=VersionAuthority.SEMAPACT.value,
        )
        tag_pattern = self._config.get(
            "release.tagPattern",
            env_var="SEMAPACT_RELEASE_TAG_PATTERN",
            default=None,
        )

        try:
            return VersionAuthorityConfig(
                authority=authority,
                tag_pattern=tag_pattern,
            )
        except PydanticValidationError as exc:
            message = exc.errors()[0].get("msg", "invalid version authority configuration")
            raise ValidationError(
                f"Invalid release version authority configuration: {message}"
            ) from exc
