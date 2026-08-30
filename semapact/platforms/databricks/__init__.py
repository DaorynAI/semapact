"""Databricks platform-access helpers."""

from semapact.platforms.databricks.client import create_databricks_workspace_client
from semapact.platforms.databricks.discovery import discover_databricks_tables

__all__ = [
    "create_databricks_workspace_client",
    "discover_databricks_tables",
]
