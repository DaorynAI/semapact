from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from open_data_contract_standard.model import OpenDataContractStandard

from semapact.core import loader as contract_loader
from semapact.utils.schema_utils import contract_to_dict


def parse_yaml_text(source_yaml: str) -> dict[str, Any]:
    """Parse ODCS YAML text into a canonical contract mapping."""
    try:
        model = OpenDataContractStandard.from_string(source_yaml)
    except TypeError as exc:
        from semapact.exceptions import ValidationError

        raise ValidationError("YAML content must be a mapping object") from exc
    return model.model_dump(by_alias=True, exclude_none=True)


def dump_yaml_text(payload: dict[str, Any]) -> str:
    """Serialize a contract mapping through the ODCS model definition."""
    model = OpenDataContractStandard.model_validate(payload)
    return model.to_yaml()


def read_yaml_text(path: str | Path) -> str:
    """Read raw YAML text from supported storage backends."""
    path_str = str(path)
    if _is_local_path(path_str):
        resolved = _resolve_local_path(path)
        return resolved.read_text(encoding="utf-8")
    return contract_loader.read_contract_text(
        path_str, contract_loader._resolve_runtime_context(None)
    )


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load YAML document as a mapping."""
    payload = yaml.safe_load(read_yaml_text(path))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML content must be a mapping object: {path}")
    return payload


def dump_yaml(
    payload: dict[str, Any] | OpenDataContractStandard, path: str | Path
) -> Path:
    """Write ODCS mapping or model payload to YAML."""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        yaml.safe_dump(contract_to_dict(payload), sort_keys=False), encoding="utf-8"
    )
    return resolved


def load_yaml_metadata(
    path: str | Path, keys: list[str] | tuple[str, ...]
) -> dict[str, str]:
    """Read only top-level scalar metadata keys from a YAML file.

    This avoids deserializing the full contract when the UI only needs catalog
    metadata such as id, name, version, status, or tenant.
    """
    wanted = {str(key) for key in keys}
    metadata: dict[str, str] = {}

    document = yaml.compose(read_yaml_text(path))
    if not isinstance(document, yaml.nodes.MappingNode):
        return metadata

    for key_node, value_node in document.value:
        if not isinstance(key_node, yaml.nodes.ScalarNode):
            continue

        key = str(key_node.value)
        if key not in wanted or key in metadata:
            continue

        if isinstance(value_node, yaml.nodes.ScalarNode):
            metadata[key] = str(value_node.value)

        if len(metadata) == len(wanted):
            break

    return metadata


def list_yaml_documents(root: str | Path) -> list[str]:
    """List YAML contract documents under a local or ADLS2 root path."""
    root_str = str(root)
    if contract_loader.is_uc_volume_path(root_str):
        return _list_local_yaml_documents(
            contract_loader.normalize_uc_volume_local_path(root_str)
        )
    if _is_local_path(root_str):
        return _list_local_yaml_documents(root)
    if contract_loader.is_adls2_path(root_str):
        return contract_loader.list_adls2_paths(root_str)
    raise ValueError(f"Unsupported contract storage root: {root}")


def _list_local_yaml_documents(root: str | Path) -> list[str]:
    resolved = _resolve_local_path(root)
    if resolved.is_file():
        return [str(resolved)] if _is_yaml_name(resolved.name) else []
    if not resolved.exists():
        return []

    paths = [*resolved.rglob("*.yaml"), *resolved.rglob("*.yml")]
    return [
        str(path.resolve())
        for path in sorted(paths, key=lambda item: str(item).lower())
    ]


def _resolve_local_path(path: str | Path) -> Path:
    parsed = urlparse(str(path))
    if parsed.scheme == "file":
        from urllib.request import url2pathname

        return Path(url2pathname(parsed.path)).expanduser().resolve()
    return Path(path).expanduser().resolve()


def _is_local_path(path: str) -> bool:
    return contract_loader.is_local_path(path)


def _is_yaml_name(name: str) -> bool:
    lowered = str(name).lower()
    return lowered.endswith(".yaml") or lowered.endswith(".yml")


# Example usage:
# contract = load_yaml("contracts/orders.yaml")
# dump_yaml(contract, "artifacts/orders.yaml")
