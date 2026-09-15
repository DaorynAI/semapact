"""Single implementation for Unity Catalog contract imports.

This module consolidates the Unity import logic that was previously duplicated
in ``semapact.interfaces.cli`` and ``semapact.orchestrator.pipeline``.

Environment variable mutation is isolated inside a context manager so it cannot
leak into concurrent operations.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Iterator

from datacontract.data_contract import DataContract
from open_data_contract_standard.model import OpenDataContractStandard

from semapact.importers.unity_relationships import (
    enrich_unity_contract_relationships,
)

LOGGER = logging.getLogger(__name__)


@contextlib.contextmanager
def _databricks_env(
    workspace_url: str | None, token: str | None, profile: str | None
) -> Iterator[None]:
    """Temporarily set Databricks env vars and restore them on exit.

    This context manager ensures the process-global environment is restored
    even when the import raises, preventing credential leaks across calls.
    """
    env_keys = (
        "DATACONTRACT_DATABRICKS_SERVER_HOSTNAME",
        "DATACONTRACT_DATABRICKS_TOKEN",
        "DATABRICKS_CONFIG_PROFILE",
    )
    backup = {key: os.environ.get(key) for key in env_keys}
    if workspace_url:
        os.environ["DATACONTRACT_DATABRICKS_SERVER_HOSTNAME"] = workspace_url
    if token:
        os.environ["DATACONTRACT_DATABRICKS_TOKEN"] = token
    if profile:
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
    try:
        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def import_unity_contract(
    *,
    table_fqn: str,
    workspace_url: str | None = None,
    token: str | None = None,
) -> OpenDataContractStandard:
    """Import Unity Catalog metadata into ODCS using datacontract-cli.

    Runtime lineage is deliberately excluded from this importer. Lineage and
    query history are observation evidence rather than authoritative contract
    semantics and therefore must not mutate the imported ODCS contract.

    Raises ``ValueError`` when required credentials are missing.
    """
    from semapact.core.config import config_manager

    workspace_url = workspace_url or config_manager.get("databricks.workspace_url")
    token = token or config_manager.get("databricks.token")
    profile = config_manager.get("databricks.profile")

    if not profile and (not workspace_url or not token):
        raise ValueError(
            "databricks.workspace_url and databricks.token (or databricks.profile) are required for Unity Catalog imports"
        )

    LOGGER.info("Importing Unity Catalog contract: %s", table_fqn)
    with _databricks_env(workspace_url, token, profile):
        imported = DataContract.import_from_source(
            format="unity",
            source=None,
            unity_table_full_name=[table_fqn],
        )
        return enrich_unity_contract_relationships(
            imported,
            table_fqn=table_fqn,
            workspace_url=workspace_url,
            token=token,
        )
