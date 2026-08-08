from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.constants import (
    EDITABLE_PROPERTY_FIELDS,
    EDITABLE_SCHEMA_FIELDS,
    READ_ONLY_CONTRACT_FIELDS,
)
from semapact.utils.schema_utils import (
    contract_to_dict,
    contract_to_model,
    ensure_schema_key,
)

LOGGER = logging.getLogger(__name__)


def normalize_draft_contract(
    draft_contract: OpenDataContractStandard | dict[str, Any],
    main_contract: OpenDataContractStandard | dict[str, Any],
) -> dict[str, Any]:
    """Preserve non-editable fields from the main contract in a user draft.

    The normalizer is ODCS-aware:
    - both inputs are first normalized into ``OpenDataContractStandard``
    - schema and property preservation aligns by ODCS names, not list position

    Version is intentionally not preserved here because release/version
    management is handled by the delivery pipeline.
    """
    draft_model = contract_to_model(draft_contract)
    main_model = contract_to_model(main_contract)

    normalized = contract_to_dict(draft_model)
    main_payload = contract_to_dict(main_model)

    LOGGER.debug("Normalizing draft payload against main contract %s", main_model.id)

    for field in READ_ONLY_CONTRACT_FIELDS:
        if field in main_payload:
            normalized[field] = deepcopy(main_payload[field])
        else:
            normalized.pop(field, None)

    _preserve_schema_and_property_fields(normalized, main_model, main_payload)
    return normalized


def _preserve_schema_and_property_fields(
    draft_contract: dict[str, Any],
    main_contract: OpenDataContractStandard,
    main_payload: dict[str, Any],
) -> None:
    schema_key = ensure_schema_key(draft_contract)
    draft_schemas = draft_contract.get(schema_key)
    main_schemas = main_payload.get(schema_key)
    if not isinstance(draft_schemas, list) or not isinstance(main_schemas, list):
        return

    main_schema_lookup = _schema_lookup(main_contract.schema_ or [], main_schemas)

    normalized_schemas: list[Any] = []
    for draft_schema in draft_schemas:
        if not isinstance(draft_schema, dict):
            normalized_schemas.append(draft_schema)
            continue

        schema_name = _schema_name_from_dict(draft_schema)
        matched = main_schema_lookup.get(schema_name)
        if matched is None:
            normalized_schemas.append(draft_schema)
            continue

        main_schema_model, main_schema_payload = matched
        normalized_schemas.append(
            _preserve_schema_fields(
                draft_schema, main_schema_model, main_schema_payload
            )
        )

    draft_contract[schema_key] = normalized_schemas


def _preserve_schema_fields(
    draft_schema: dict[str, Any],
    main_schema: SchemaObject,
    main_schema_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = deepcopy(draft_schema)
    for field_name, value in main_schema_payload.items():
        if field_name in EDITABLE_SCHEMA_FIELDS:
            continue
        normalized[field_name] = deepcopy(value)

    for field_name in list(normalized.keys()):
        if field_name in EDITABLE_SCHEMA_FIELDS:
            continue
        if field_name not in main_schema_payload:
            normalized.pop(field_name, None)

    draft_properties = normalized.get("properties")
    main_properties = main_schema_payload.get("properties")
    if isinstance(draft_properties, list) and isinstance(main_properties, list):
        main_property_lookup = _property_lookup(
            main_schema.properties or [], main_properties
        )
        normalized_properties: list[Any] = []
        for draft_property in draft_properties:
            if not isinstance(draft_property, dict):
                normalized_properties.append(draft_property)
                continue

            property_name = _property_name_from_dict(draft_property)
            matched = main_property_lookup.get(property_name)
            if matched is None:
                normalized_properties.append(draft_property)
                continue

            main_property_model, main_property_payload = matched
            normalized_properties.append(
                _preserve_property_fields(
                    draft_property, main_property_model, main_property_payload
                )
            )
        normalized["properties"] = normalized_properties

    return normalized


def _preserve_property_fields(
    draft_property: dict[str, Any],
    main_property: SchemaProperty,
    main_property_payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = deepcopy(draft_property)
    for field_name, value in main_property_payload.items():
        if field_name in EDITABLE_PROPERTY_FIELDS:
            continue
        normalized[field_name] = deepcopy(value)

    for field_name in list(normalized.keys()):
        if field_name in EDITABLE_PROPERTY_FIELDS:
            continue
        if field_name not in main_property_payload:
            normalized.pop(field_name, None)

    draft_children = normalized.get("properties")
    main_children = main_property_payload.get("properties")
    if isinstance(draft_children, list) and isinstance(main_children, list):
        child_lookup = _property_lookup(main_property.properties or [], main_children)
        normalized_children: list[Any] = []
        for draft_child in draft_children:
            if not isinstance(draft_child, dict):
                normalized_children.append(draft_child)
                continue

            child_name = _property_name_from_dict(draft_child)
            matched = child_lookup.get(child_name)
            if matched is None:
                normalized_children.append(draft_child)
                continue

            main_child_model, main_child_payload = matched
            normalized_children.append(
                _preserve_property_fields(
                    draft_child, main_child_model, main_child_payload
                )
            )
        normalized["properties"] = normalized_children

    draft_items = normalized.get("items")
    main_items = main_property.items
    main_items_payload = main_property_payload.get("items")
    if (
        isinstance(draft_items, dict)
        and isinstance(main_items, SchemaProperty)
        and isinstance(main_items_payload, dict)
    ):
        normalized["items"] = _preserve_property_fields(
            draft_items, main_items, main_items_payload
        )

    return normalized


def _schema_lookup(
    schemas: list[SchemaObject],
    schema_payloads: list[dict[str, Any]],
) -> dict[str, tuple[SchemaObject, dict[str, Any]]]:
    lookup: dict[str, tuple[SchemaObject, dict[str, Any]]] = {}
    for schema_model, schema_payload in zip(schemas, schema_payloads, strict=False):
        schema_name = _schema_name(schema_model)
        if schema_name:
            lookup[schema_name] = (schema_model, schema_payload)
    return lookup


def _property_lookup(
    properties: list[SchemaProperty],
    property_payloads: list[dict[str, Any]],
) -> dict[str, tuple[SchemaProperty, dict[str, Any]]]:
    lookup: dict[str, tuple[SchemaProperty, dict[str, Any]]] = {}
    for property_model, property_payload in zip(
        properties, property_payloads, strict=False
    ):
        property_name = _property_name(property_model)
        if property_name:
            lookup[property_name] = (property_model, property_payload)
    return lookup


def _schema_name(schema: SchemaObject) -> str:
    return str(schema.name or "").strip()


def _property_name(property_obj: SchemaProperty) -> str:
    return str(property_obj.name or "").strip()


def _schema_name_from_dict(schema: dict[str, Any]) -> str:
    return str(schema.get("name", "") or "").strip()


def _property_name_from_dict(property_obj: dict[str, Any]) -> str:
    return str(property_obj.get("name", "") or "").strip()
