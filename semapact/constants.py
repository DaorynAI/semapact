"""Shared SemaPact constants.

This module is the single source of truth for editor, draft-normalization,
and exporter constants that are reused across layers.
"""

from __future__ import annotations

TYPE_OPTIONS = ["string", "int", "bigint", "decimal", "boolean", "timestamp"]
LIFECYCLE_OPTIONS = ["draft", "active", "deprecated"]
CONTRACT_STATUS_OPTIONS = ["draft", "active", "deprecated", "retired"]
QUALITY_TYPE_OPTIONS = ["GE", "SQL"]
QUALITY_SEVERITY_OPTIONS = ["warning", "error"]
CHANGE_FILTER_OPTIONS = ["ALL", "BREAKING", "ADDED", "MODIFIED", "DEPRECATED"]

TABLE_RULE_COLUMN = "__table__"
DEFAULT_QUALITY_TYPE = QUALITY_TYPE_OPTIONS[0]
DEFAULT_QUALITY_SEVERITY = QUALITY_SEVERITY_OPTIONS[0]

READ_ONLY_CONTRACT_FIELDS = (
    "apiVersion",
    "kind",
    "id",
    "name",
    "status",
    "domain",
    "dataProduct",
    "tenant",
    "servers",
)

EDITABLE_SCHEMA_FIELDS = {
    "businessName",
    "description",
    "tags",
    "quality",
    "properties",
}
EDITABLE_PROPERTY_FIELDS = {
    "businessName",
    "description",
    "examples",
    "tags",
    "classification",
    "transformDescription",
    "quality",
    "properties",
    "items",
}

TECHNICAL_PROPERTY_KEYS = {
    "name",
    "physicalName",
    "logicalType",
    "physicalType",
    "required",
    "items",
    "additionalProperties",
    "logicalTypeOptions",
    "format",
    "pattern",
}

BUSINESS_PROPERTY_KEYS = {"businessName", "description", "examples", "tags"}

UNITY_RELATIONSHIPS_IMPORTED_KEY = "semapact.unity.relationshipsImported"
UNITY_RELATIONSHIPS_COUNT_KEY = "semapact.unity.relationshipsCount"
UNITY_RELATIONSHIPS_REASON_KEY = "semapact.unity.relationshipsReason"
UNITY_CONSTRAINT_NAME_KEY = "semapact.unity.constraintName"

# Enricher Prompts
LABEL_SYSTEM_PROMPT_TEMPLATE = """
You are an expert Data Architect and Graph Database Modeler working within the following business domain: [{domain_context}].
Your task is to infer the semantic relationship (edge label) between two database tables based on their foreign key references and table descriptions.

CRITICAL RULES:
1. You MUST output ONLY valid JSON.
2. The JSON must have exactly one key: "edge_label".
3. The value MUST be a concise VERB or VERB PHRASE (1 to 3 words maximum).
4. The value MUST be strictly UPPERCASE with UNDERSCORES separating words (e.g., HAS_ACCOUNT, PURCHASED, LIVES_AT).
5. The verb should describe the action from the SOURCE table to the TARGET table.
6. AVOID overly generic verbs like BELONGS_TO, HAS, or PART_OF unless no more specific business action (e.g., WORKS_IN, CATEGORIZED_BY, LOCATED_AT) can be inferred.
"""

LABEL_USER_PROMPT_TEMPLATE = """
Infer the relationship for the following schema definition:

- Source Entity: {source_table_name}
  - Source Description: {source_table_description}
- Source Column: {source_column_name}
- Target Entity (Referenced): {target_table_name}
  - Target Description: {target_table_description}
- Mapping/Junction Table Context (if applicable): {junction_table_name}

Examples:
- Source: 'orders', Target: 'customers' -> {{"edge_label": "PLACED_BY"}}
- Source: 'employees', Target: 'departments' -> {{"edge_label": "WORKS_IN"}}
- Source: 'users', Target: 'projects', Mapping Context: 'user_project_mapping' -> {{"edge_label": "PARTICIPATES_IN"}}

Please provide the strictly formatted JSON output for the current schema:
"""

JOIN_SYSTEM_PROMPT_TEMPLATE = """
You are an expert Data Architect and Graph Database Modeler working within the following business domain: [{domain_context}].
Your task is to infer potential semantic relationships (joins) between columns of two database tables.

CRITICAL RULES:
1. You MUST output ONLY valid JSON.
2. The JSON must contain a single key: "potential_joins", whose value is a list of objects.
3. Each object in the list must represent a highly probable join between a column in the Source Entity and a column in the Target Entity.
4. Each object must have exactly the following keys:
   - "source_column": the name of the column in the Source Entity.
   - "target_column": the name of the column in the Target Entity.
   - "edge_label": a concise VERB or VERB PHRASE (1 to 3 words maximum), strictly UPPERCASE with UNDERSCORES. It should describe the action from the Source Entity to the Target Entity.
   - "confidence": a float between 0.0 and 1.0 representing your confidence in this join.
5. Only return relationships that make strong semantic sense. If no logical joins exist, return an empty list for "potential_joins".
6. PREFER specific business actions (e.g., 'OPERATES_IN', 'MANUFACTURED_BY') over generic structural descriptions (e.g., 'HAS_COUNTRY', 'BELONGS_TO').
"""

JOIN_USER_PROMPT_TEMPLATE = """
Infer potential joins for the following two tables.

- Source Entity: {source_table_name}
  - Description: {source_table_description}
  - Columns: {source_columns}
- Target Entity: {target_table_name}
  - Description: {target_table_description}
  - Columns: {target_columns}

Please provide the strictly formatted JSON output for potential joins between these entities:
"""

TABLE_DESC_SYSTEM_PROMPT_TEMPLATE = """
You are an expert Data Architect working within the following business domain: [{domain_context}].
Your task is to infer a clear, concise, and business-friendly description for a database table.

CRITICAL RULES:
1. You MUST output ONLY valid JSON.
2. The JSON must contain a single key: "description".
3. Provide a clear description that explains the purpose of the table and the data it holds.
4. Your output description will be tagged later, so do NOT manually include [LLM_INFERRED] in your response string.
5. If Authoritative Definitions (e.g., Confluence links, Purview documentation) are provided, use them as your primary source of truth for business context and terminology.
"""

TABLE_DESC_USER_PROMPT_TEMPLATE = """
Infer the description for the following table.

- Entity Name: {table_name}
- Columns: {columns_info}
- Authoritative Definitions: {authoritative_definitions}

Please provide the strictly formatted JSON output for the table description:
"""

COLUMN_DESC_SYSTEM_PROMPT_TEMPLATE = """
You are an expert Data Architect working within the following business domain: [{domain_context}].
Your task is to infer a clear, concise, and business-friendly description for a specific column within a database table.

CRITICAL RULES:
1. You MUST output ONLY valid JSON.
2. The JSON must contain a single key: "description".
3. Provide a clear description that explains the purpose of the column.
4. Use the context of the table and other columns to make an educated guess.
5. Your output description will be tagged later, so do NOT manually include [LLM_INFERRED] in your response string.
6. If Authoritative Definitions are provided, rely on them heavily to understand internal terminology and business meaning.
"""

COLUMN_DESC_USER_PROMPT_TEMPLATE = """
Infer the description for the following column.

- Entity Name: {table_name}
  - Entity Description: {table_description}
- Target Column: {column_name} (Type: {column_type})
- Other Columns in Table: {other_columns_info}
- Authoritative Definitions: {authoritative_definitions}

Please provide the strictly formatted JSON output for the column description:
"""

QUALITY_SUGGESTION_SYSTEM_PROMPT_TEMPLATE = """
You are an expert Data Quality Engineer working within the following business domain: [{domain_context}].
Your task is to suggest fundamental Great Expectations (GE) data quality rules for a specific column.

CRITICAL RULES:
1. You MUST output ONLY valid JSON.
2. The JSON must contain a single key: "quality_rules", whose value is a list of rule objects.
3. Each rule object MUST have:
   - "type": "GE"
   - "metric": The GE metric name (e.g., "duplicateValues", "nullValues", "invalidValues", "rowCount")
   - "mustBe": A value (e.g., 0 for counts of errors), or "mustBeBetween", etc.
   - "arguments": Optional dictionary of arguments (e.g., {"pattern": "^.+@.+$"} for regex).
4. ONLY suggest rules that add value. DO NOT suggest rules that are already covered by schema constraints.
   - For example, if a column is `required: true`, do NOT suggest a nullValues check.
   - If a column is a primary key, do NOT suggest duplicateValues unless you think it's necessary to explicitly test it.
5. Base your suggestions heavily on the column's description, type, and name.
   - Examples of valid rules:
     - Email formats -> {"type": "GE", "metric": "invalidValues", "arguments": {"pattern": "^.+@.+$"}, "mustBe": 0}
     - Status values -> {"type": "GE", "metric": "invalidValues", "arguments": {"valueSet": ["ACTIVE", "INACTIVE"]}, "mustBe": 0}
6. If Authoritative Definitions are provided, strictly align any allowed values (valueSet), formats, or data quality rules with those enterprise definitions.
"""

QUALITY_SUGGESTION_USER_PROMPT_TEMPLATE = """
Suggest Data Quality rules for the following column.

- Entity Name: {table_name}
- Column: {column_name}
  - Description: {column_description}
  - Type: {column_type}
  - Required (not null): {is_required}
  - Primary Key: {is_primary_key}
- Authoritative Definitions: {authoritative_definitions}

Please provide the strictly formatted JSON output with suggested GE rules:
"""
