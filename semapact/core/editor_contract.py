"""Compatibility facade for editor helpers.

New code should import from:
- `semapact.core.editor_semantics`
- `semapact.core.editor_rows`

This module remains as a stable compatibility layer while the editor codebase
is being split into ODCS-aware semantics and dict-based UI row adapters.
"""

from __future__ import annotations

from semapact.core.editor_rows import (
    add_field,
    add_quality_rule,
    apply_field_detail,
    apply_quality_rows,
    apply_quick_field_rows,
    field_by_name,
    is_blank_quality_row,
    is_blank_quick_field_row,
    optional_int,
    quality_rows,
    rule_condition,
    selected_schema_field_names,
    tags_to_text,
    text_to_tags,
)
from semapact.core.editor_semantics import (
    contract_description_part,
    contract_tags,
    description_mapping,
    field_declared_lifecycle_status,
    field_examples_text,
    field_lifecycle_status,
    normalize_tags,
    schema_items,
    set_contract_description_part,
    set_contract_tags_list,
    set_field_examples,
    set_field_lifecycle_status,
    set_mapping_text,
)

__all__ = [
    "add_field",
    "add_quality_rule",
    "apply_field_detail",
    "apply_quality_rows",
    "apply_quick_field_rows",
    "contract_description_part",
    "contract_tags",
    "description_mapping",
    "field_by_name",
    "field_declared_lifecycle_status",
    "field_examples_text",
    "field_lifecycle_status",

    "is_blank_quality_row",
    "is_blank_quick_field_row",
    "normalize_tags",
    "optional_int",
    "quality_rows",
    "rule_condition",
    "schema_items",
    "selected_schema_field_names",
    "set_contract_description_part",
    "set_contract_tags_list",
    "set_field_examples",
    "set_field_lifecycle_status",
    "set_mapping_text",
    "tags_to_text",
    "text_to_tags",
]
