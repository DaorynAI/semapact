import os
import abc
from pathlib import Path
from typing import Any, List, Optional
import logging

LOGGER = logging.getLogger(__name__)


class CloudStorageAdapter(abc.ABC):
    """
    Base class for cloud and local storage adapters used to discover Delta Tables
    or perform generic directory scanning across different filesystems.
    """

    @abc.abstractmethod
    def discover_delta_tables(self, source_uri: str, credential: Any = None) -> List[str]:
        """
        Scan a source directory for Delta Tables. A Delta Table is identified
        by the presence of a `_delta_log` directory.
        If `source_uri` itself is a Delta Table, it should return `[source_uri]`.
        """
        pass


class LocalStorageAdapter(CloudStorageAdapter):
    def discover_delta_tables(self, source_uri: str, credential: Any = None) -> List[str]:
        if source_uri.startswith("file://"):
            import urllib.request
            import urllib.parse
            parsed = urllib.parse.urlparse(source_uri)
            source_uri = urllib.request.url2pathname(parsed.path)

        root_path = Path(source_uri)
        if not root_path.exists():
            raise FileNotFoundError(f"Source directory not found: {source_uri}")

        if not root_path.is_dir():
            raise ValueError(f"Source is not a directory: {source_uri}")

        # Check if the root itself is a delta table
        if (root_path / "_delta_log").is_dir():
            return [source_uri]

        # Scan immediate subdirectories
        table_uris = []
        try:
            for item in root_path.iterdir():
                if item.is_dir() and (item / "_delta_log").is_dir():
                    table_uris.append(str(item.absolute()))
        except PermissionError as e:
            LOGGER.warning(f"Permission error scanning local directory: {e}")

        return sorted(table_uris)


class AzureADLSAdapter(CloudStorageAdapter):
    def discover_delta_tables(self, source_uri: str, credential: Any = None) -> List[str]:
        from semapact.core.loader import _create_adls2_filesystem_client, _parse_adls2_path
        
        parsed = _parse_adls2_path(source_uri)
        relative_root = parsed["relative_path"] or ""
        
        fs_client = _create_adls2_filesystem_client(source_uri, credential=credential)
        
        table_uris = []
        # ADLS2 get_paths can be recursive, but checking for _delta_log specifically:
        # If the root itself is a delta table:
        try:
            paths = list(fs_client.get_paths(path=relative_root, recursive=True))
            
            # Check if root is delta table (i.e. contains _delta_log right under relative_root)
            delta_log_suffix = "_delta_log"
            
            # We want to find all unique parent directories of "_delta_log"
            delta_table_paths = set()
            for path_item in paths:
                path_name = path_item.name
                if path_name.endswith(delta_log_suffix) or f"{delta_log_suffix}/" in path_name:
                    # Extract the table root path
                    # e.g. domain/my_table/_delta_log/0000.json -> domain/my_table
                    idx = path_name.find(delta_log_suffix)
                    table_relative_path = path_name[:idx].rstrip("/")
                    delta_table_paths.add(table_relative_path)
            
            for tbl_path in delta_table_paths:
                # Reconstruct full abfss:// URI
                import urllib.parse
                host = urllib.parse.urlparse(parsed['account_url']).hostname
                uri = f"abfss://{parsed['filesystem']}@{host}/{tbl_path}"
                table_uris.append(uri)
                
            return sorted(table_uris)

        except Exception as exc:
            LOGGER.error(f"Failed to scan ADLS2 directory for delta tables: {exc}")
            raise


class S3Adapter(CloudStorageAdapter):
    def discover_delta_tables(self, source_uri: str, credential: Any = None) -> List[str]:
        try:
            import boto3
            import s3fs
        except ImportError as exc:
            raise RuntimeError(
                "S3 storage adapter requires boto3 and s3fs. "
                "Install with `pip install semapact[s3]`."
            ) from exc

        # Initialize s3fs
        # In a real environment, credential could be a boto3 session or credentials dictionary.
        kwargs = {}
        if isinstance(credential, dict):
            kwargs.update(credential)
        fs = s3fs.S3FileSystem(**kwargs)
        
        # Remove s3:// prefix for fsspec operations
        s3_path = source_uri
        if s3_path.startswith("s3://"):
            s3_path = s3_path[5:]
            
        try:
            # Check if root is a delta table
            if fs.exists(f"{s3_path}/_delta_log") and fs.isdir(f"{s3_path}/_delta_log"):
                return [source_uri]
            
            table_uris = []
            # List immediate subdirectories
            for item in fs.ls(s3_path, detail=True):
                if item["type"] == "directory":
                    dir_path = item["name"]
                    if fs.exists(f"{dir_path}/_delta_log") and fs.isdir(f"{dir_path}/_delta_log"):
                        table_uris.append(f"s3://{dir_path}")
                        
            return sorted(table_uris)
        except Exception as exc:
            LOGGER.error(f"Failed to scan S3 directory for delta tables: {exc}")
            raise


class StorageAdapterFactory:
    @staticmethod
    def get_adapter(uri: str) -> CloudStorageAdapter:
        if not uri:
            return LocalStorageAdapter()
            
        uri_lower = uri.lower()
        if uri_lower.startswith("abfss://"):
            return AzureADLSAdapter()
        elif uri_lower.startswith("s3://"):
            return S3Adapter()
        elif uri_lower.startswith("gs://"):
            raise NotImplementedError("GCS is not yet supported in StorageAdapterFactory.")
        else:
            return LocalStorageAdapter()
