"""ODCS-aware editor semantics helpers.

These helpers deal with contract and property semantics rather than table-row
shaping. They should prefer ODCS models when reading or reasoning about
contract structure.
"""

from __future__ import annotations

from typing import Any

from open_data_contract_standard.model import (
    CustomProperty,
    Description,
    OpenDataContractStandard,
    SchemaProperty,
    Server,
)

from semapact.constants import TYPE_OPTIONS
from semapact.utils.schema_utils import contract_to_model

ContractInput = OpenDataContractStandard | dict[str, Any]
PropertyInput = SchemaProperty | dict[str, Any]


def normalize_tags(tags: Any) -> list[str]:
    """Normalize tag values into a stable, de-duplicated list."""
    if not isinstance(tags, list):
        return []

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = str(tag).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized_tags.append(normalized)
    return normalized_tags


def set_mapping_text(mapping: dict[str, Any], key: str, value: str) -> None:
    """Set or remove a string mapping field."""
    if value.strip():
        mapping[key] = value
    else:
        mapping.pop(key, None)


def description_mapping(
    contract: dict[str, Any], *, create: bool = False
) -> dict[str, Any]:
    """Return the ODCS root description mapping."""
    description = contract.get("description")
    if isinstance(description, dict):
        return description
    if create:
        contract["description"] = (
            {"purpose": description}
            if isinstance(description, str) and description.strip()
            else {}
        )
        return contract["description"]
    return {}


def contract_description_part(contract: ContractInput, part: str) -> str:
    """Resolve a structured contract description field."""
    model = contract_to_model(contract)
    description = model.description or Description()
    return str(getattr(description, part, "") or "")


def contract_name(contract: ContractInput) -> str:
    """Resolve contract name."""
    return str(contract_to_model(contract).name or "")


def contract_version(contract: ContractInput) -> str:
    """Resolve contract version."""
    return str(contract_to_model(contract).version or "")


def contract_status(contract: ContractInput) -> str:
    """Resolve contract status."""
    return str(contract_to_model(contract).status or "")


def contract_domain(contract: ContractInput) -> str:
    """Resolve contract domain."""
    return str(contract_to_model(contract).domain or "")


def contract_data_product(contract: ContractInput) -> str:
    """Resolve contract data product."""
    return str(contract_to_model(contract).dataProduct or "")


def contract_tenant(contract: ContractInput) -> str:
    """Resolve contract tenant."""
    return str(contract_to_model(contract).tenant or "")


def contract_id(contract: ContractInput) -> str:
    """Resolve contract identifier."""
    return str(contract_to_model(contract).id or "")


def contract_api_version(contract: ContractInput) -> str:
    """Resolve ODCS API version."""
    return str(contract_to_model(contract).apiVersion or "")


def contract_kind(contract: ContractInput) -> str:
    """Resolve ODCS kind."""
    return str(contract_to_model(contract).kind or "")


def set_contract_description_part(
    contract: dict[str, Any], part: str, value: str
) -> None:
    """Persist a structured contract description field."""
    description = description_mapping(contract, create=True)
    set_mapping_text(description, part, value)
    if not description:
        contract.pop("description", None)


def contract_tags(contract: ContractInput) -> list[str]:
    """Resolve contract tags."""
    model = contract_to_model(contract)
    return normalize_tags(model.tags or [])


def set_contract_tags_list(contract: dict[str, Any], tags: list[str]) -> None:
    """Persist contract tags from a normalized list."""
    contract["tags"] = normalize_tags(tags)


def schema_items(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the contract schema list."""
    if isinstance(contract.get("schema"), list):
        return contract["schema"]
    if isinstance(contract.get("schemas"), list):
        return contract["schemas"]
    contract["schema"] = []
    return contract["schema"]


def schema_label(contract: ContractInput, index: int) -> str:
    """Format a schema label for selection."""
    schemas = contract_to_model(contract).schema_ or []
    if 0 <= index < len(schemas):
        return str(schemas[index].name or f"schema_{index + 1}")
    return f"schema_{index + 1}"


def field_lifecycle_status(field_obj: PropertyInput) -> str:
    """Resolve field lifecycle status."""
    if isinstance(field_obj, dict):
        status = field_obj.get("status")
        if status is not None:
            return str(status)
    model = _property_model(field_obj)
    for item in model.customProperties or []:
        if str(item.property or "").strip().lower() == "lifecyclestatus":
            return str(item.value or "")
    return ""


def field_option_label(field_obj: PropertyInput, index: int) -> str:
    """Format a field label for display."""
    field_name = str(_property_model(field_obj).name or "").strip()
    return field_name or f"field_{index + 1}"


def set_field_lifecycle_status(field_obj: dict[str, Any], value: Any) -> None:
    """Persist field lifecycle status."""
    status_value = str(value or "").strip() or "draft"
    field_obj["status"] = status_value
    custom_properties = [
        item.model_dump(by_alias=True, exclude_none=True)
        for item in _custom_property_models(field_obj.get("customProperties", []) or [])
        if str(item.property or "").strip().lower() != "lifecyclestatus"
    ]
    custom_properties.append(
        CustomProperty(property="lifecycleStatus", value=status_value).model_dump(
            by_alias=True, exclude_none=True
        )
    )
    field_obj["customProperties"] = custom_properties


def field_examples_text(field_obj: PropertyInput) -> str:
    """Render examples as a newline-separated text block."""
    examples = _property_model(field_obj).examples
    if not isinstance(examples, list):
        return ""
    return "\n".join(str(example) for example in examples if str(example).strip())


def field_type(field_obj: PropertyInput) -> str:
    """Resolve the editor type for a field."""
    model = _property_model(field_obj)
    type_value = str(model.logicalType or model.physicalType or "string")
    return type_value if type_value in TYPE_OPTIONS else "string"


def set_field_examples(field_obj: dict[str, Any], examples_text: str) -> None:
    """Persist examples from a newline-separated text block."""
    examples = [line.strip() for line in examples_text.splitlines() if line.strip()]
    if examples:
        field_obj["examples"] = examples
    else:
        field_obj.pop("examples", None)


def _property_model(field_obj: PropertyInput) -> SchemaProperty:
    if isinstance(field_obj, SchemaProperty):
        return field_obj
    allowed_keys = SchemaProperty.model_fields.keys()
    payload = {key: value for key, value in field_obj.items() if key in allowed_keys}
    return SchemaProperty.model_validate(payload)


def _custom_property_models(values: list[Any]) -> list[CustomProperty]:
    models: list[CustomProperty] = []
    for value in values:
        if isinstance(value, CustomProperty):
            models.append(value)
        elif isinstance(value, dict):
            try:
                from pydantic import ValidationError as PydanticValidationError

                models.append(CustomProperty.model_validate(value))
            except PydanticValidationError:
                continue
    return models


def server_items(contract: ContractInput) -> list[dict[str, Any]]:
    """Return server objects defined on the contract as UI-friendly mappings."""
    model = contract_to_model(contract)
    return [
        server.model_dump(by_alias=True, exclude_none=True)
        for server in model.servers or []
    ]


def server_label(server: Server | dict[str, Any]) -> str:
    """Format a server label for selection."""
    if isinstance(server, Server):
        server_id = str(server.id or "").strip()
        server_name = str(server.server or "").strip()
        environment = str(server.environment or "").strip()
    else:
        server_id = str(server.get("id", "") or "").strip()
        server_name = str(server.get("server", "") or "").strip()
        environment = str(server.get("environment", "") or "").strip()

    if server_id and environment:
        return f"{server_id} ({environment})"
    if server_id:
        return server_id
    if server_name and environment:
        return f"{server_name} ({environment})"
    return server_name or "server"
