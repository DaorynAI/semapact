"""Databricks implementation of the platform-neutral runtime provider seam."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from semapact.observation.databricks import observe_databricks_table
from semapact.observation.fingerprint import with_observed_state_fingerprint
from semapact.observation.models import ObservedAssetIdentity, ObservedPlatformState
from semapact.observation.providers import RuntimeAssetBinding, RuntimeAssetSpec
from semapact.platforms.databricks.target import parse_databricks_runtime_target


class DatabricksRuntimeProvider:
    """Bind and observe a governed data product in one Unity Catalog namespace."""

    key = "databricks"

    def __init__(self, *, client: Any, source_identifier: str) -> None:
        if not source_identifier.strip():
            raise ValueError("source_identifier is required")
        self._client = client
        self._source_identifier = source_identifier.strip().rstrip("/")

    def resolve_bindings(
        self,
        *,
        runtime_target: str,
        assets: Sequence[RuntimeAssetSpec],
    ) -> tuple[RuntimeAssetBinding, ...]:
        """Resolve ``catalog.schema`` plus asset physical names into UC identities."""
        namespace = parse_databricks_runtime_target(runtime_target)
        bindings = tuple(
            RuntimeAssetBinding(
                governed_asset=asset.governed_asset,
                observed_asset=ObservedAssetIdentity(
                    platform=self.key,
                    namespace=namespace,
                    asset=asset.physical_name,
                ),
            )
            for asset in assets
        )
        return tuple(sorted(bindings, key=lambda item: item.governed_asset))

    def observe(
        self,
        *,
        bindings: Sequence[RuntimeAssetBinding],
    ) -> ObservedPlatformState:
        """Observe every bound UC asset; missing tables remain absent evidence."""
        captured_at = datetime.now(timezone.utc)
        assets = []
        not_found_error = _load_databricks_not_found_error()

        for binding in sorted(bindings, key=lambda item: item.governed_asset):
            identity = binding.observed_asset
            if identity.platform.casefold() != self.key:
                raise ValueError("Databricks provider received a non-Databricks binding")
            if len(identity.namespace) != 2:
                raise ValueError(
                    "Databricks runtime asset identity requires catalog and schema namespace"
                )
            table_fqn = ".".join((*identity.namespace, identity.asset))
            try:
                observed = observe_databricks_table(
                    client=self._client,
                    table_fqn=table_fqn,
                    source_identifier=self._source_identifier,
                    captured_at=captured_at,
                )
            except not_found_error:
                continue
            assets.extend(observed.assets)

        state = ObservedPlatformState(
            platform=self.key,
            source_identifier=self._source_identifier,
            assets=tuple(assets),
            captured_at=captured_at,
            fingerprint=None,
        )
        return with_observed_state_fingerprint(state)


def _load_databricks_not_found_error() -> type[BaseException]:
    try:
        from databricks.sdk.errors import NotFound
    except ImportError as exc:
        raise RuntimeError(
            'Databricks support requires the optional extra: pip install "semapact[databricks]"'
        ) from exc
    return NotFound
