from datetime import datetime, timezone
from typing import Any
from semapact.core.loader import ContractLoader
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml
from open_data_contract_standard.model import (
    CustomProperty,
    SchemaObject,
    SchemaProperty,
)


def apply_lifecycle(args: Any, is_promote: bool) -> dict[str, Any]:
    loader = ContractLoader(runtime_context=args.runtime_context)
    contract = loader.load(args.contract)

    target_status = "active" if is_promote else "deprecated"

    if getattr(args, "property", None) and not getattr(args, "schema", None):
        raise ValueError("The '--schema' argument is required when '--property' is specified.")

    if getattr(args, "schema", None) and getattr(args, "property", None):
        _apply_property(contract, args.schema, args.property, target_status)
    elif getattr(args, "schema", None):
        _apply_schema(contract, args.schema, target_status)
    else:
        _apply_contract(contract, target_status)

    output_path = args.output or args.contract
    dump_yaml(contract_to_dict(contract), output_path)

    return {
        "contract": args.contract,
        "target_status": target_status,
        "schema": getattr(args, "schema", None),
        "property": getattr(args, "property", None),
        "output": str(output_path),
    }


def _apply_contract(contract: Any, target_status: str) -> None:
    contract.status = target_status


def _apply_schema(contract: Any, schema_name: str, target_status: str) -> None:
    for i, schema_obj in enumerate(contract.schema_ or []):
        if str(schema_obj.name or "") == schema_name:
            if target_status == "active":
                contract.schema_[i] = _promote_entity_model(schema_obj)
            else:
                contract.schema_[i] = _deprecate_entity_model(schema_obj)
            return
    raise ValueError(f"Schema '{schema_name}' not found in contract")


def _apply_property(
    contract: Any, schema_name: str, property_name: str, target_status: str
) -> None:
    for i, schema_obj in enumerate(contract.schema_ or []):
        if str(schema_obj.name or "") == schema_name:
            for j, prop in enumerate(schema_obj.properties or []):
                if str(prop.name or "") == property_name:
                    if target_status == "active":
                        contract.schema_[i].properties[j] = _promote_entity_model(prop)
                    else:
                        contract.schema_[i].properties[j] = _deprecate_entity_model(
                            prop
                        )
                    return
            raise ValueError(
                f"Property '{property_name}' not found in schema '{schema_name}'"
            )
    raise ValueError(f"Schema '{schema_name}' not found in contract")


def _promote_entity_model(
    entity: SchemaObject | SchemaProperty,
) -> SchemaObject | SchemaProperty:
    from semapact.lifecycle.merge_engine import _merge_custom_properties_models

    updated = entity.model_copy(deep=True)
    updates = [CustomProperty(property="lifecycleStatus", value="active")]
    updated.customProperties = _merge_custom_properties_models(
        updated.customProperties, updates
    )
    return updated


def _deprecate_entity_model(
    entity: SchemaObject | SchemaProperty,
) -> SchemaObject | SchemaProperty:
    from semapact.lifecycle.merge_engine import _merge_custom_properties_models

    updated = entity.model_copy(deep=True)

    updates = [CustomProperty(property="lifecycleStatus", value="deprecated")]

    # Check if deprecationDate already exists
    has_date = False
    if updated.customProperties:
        for cp in updated.customProperties:
            if str(getattr(cp, "property", "")).lower() == "deprecationdate":
                has_date = True
                break
    if not has_date:
        updates.append(
            CustomProperty(
                property="deprecationDate",
                value=datetime.now(timezone.utc).date().isoformat(),
            )
        )

    updated.customProperties = _merge_custom_properties_models(
        updated.customProperties, updates
    )

    # Add tags
    tags = getattr(updated, "tags", []) or []
    normalized = [str(tag) for tag in tags]
    if "deprecated" not in normalized:
        normalized.append("deprecated")
    normalized.sort()
    updated.tags = normalized

    return updated
