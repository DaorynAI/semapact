# Open Data Contract Standard Graph Export Specification

This document details the exact mapping rules and behavior utilized by the `GraphExporter` to serialize Open Data Contract Standard (ODCS) v3 models into Property Graph topologies (specifically Cypher and JSON representations).

## Architectural Topology

The graph adopts a highly granular **"Column as Node"** architecture, combined with **"Paths Over Joins"** philosophy.

1. **Table Nodes**: Every `SchemaObject` translates to a `Table` node.
2. **Column Nodes**: Every `SchemaProperty` translates to a `Column` node, deterministically ID'd via `{table_name}.{column_name}`.
3. **Structural Edges**: A structural `HAS_COLUMN` edge permanently connects `Table` nodes to their respective `Column` nodes.
4. **Semantic Edges**: Relationships (Foreign Keys) define paths between tables, optionally collapsing junction mapping tables.

## Mapping Rules & Extracted Properties

### Node Extracted Properties
* **Tables**: Retain `name`, `description`, `businessName`, and `dataGranularityDescription`.
* **Columns**: Retain `name`, `logicalType`, `format` (from `logicalTypeOptions.format`), `description`, `businessName`, `classification` (which determines the synthetic `is_pii` boolean), `is_primary_key`, `quality` metrics, and `examples`. Complex objects like `quality` rules (e.g., Metrics arrays) or `examples` arrays are safely dumped as inline JSON strings to prevent Cypher escaping errors.

### Relationship / Edge Rules
Open Data Contract Standard references handle relationship binding natively via two methods, both of which allow target specifications via **Short Notation** (e.g. `target_table.target_column` or `target_table`):

1. **Property-level Relationships**: Because these are defined under a specific property, the `from` field is implicit. `GraphExporter` respects this model design, leaving `from` omitted from the output edge.
2. **Schema-level Relationships**: Explicitly provide both `from_` and `to`.
3. **Source and Target Columns**:
   - When serialized, the references are explicitly captured under `source_columns` and `target_columns` edge properties instead of the base model's `from` and `to` syntax.
   - For standardization, these edge properties are strictly output as **JSON Array strings** (e.g. `"[\"id\"]"`), regardless of whether they represent a single column reference or a composite keys array.
   - Any implicit or explicit table name prefixes matching the Short Reference notation (e.g., `orders.order_id`) are systematically stripped away, retaining only the pure column name logic (e.g. `["order_id"]`).
4. **Junction Edges**: A relation table containing strictly 2 references and flagged with the ODCS `customProperty` `graph_export.is_junction_edge` evaluates as a semantic mapping edge rather than a static table. Its edge properties will dynamically absorb the collapsed Table's schema properties (such as its `name`, `description`, `businessName`, etc.).
5. **Edge Semantics & Provenance**:
   - Label semantics are overridden via the `graph_semantic.edge_label` ODCS custom property, otherwise strictly falling back to an uppercase variation of the target table name.
   - The origin of the edge is recorded via `provenance`. If `graph_semantic.provenance` is not present, it gracefully defaults to `"DDL"`. In LLM-enriched structures, it may take values like `"LLM_INFERRED"` and attach a secondary `confidence` score.

---

## Output Serialization Samples

The below samples display exactly how structures are emitted using `--format graph --export-args '{"format": "cypher"}'` or JSON equivalently.

### 1. Table Node

**Cypher**:
```cypher
CREATE (n_0:Table {
  name: "users",
  businessName: "Users Table",
  dataGranularityDescription: "One row per user",
  id: "users"
})
```

**JSON**:
```json
{
  "id": 0,
  "original_id": "users",
  "type": "Table",
  "properties": {
    "name": "users",
    "businessName": "Users Table",
    "dataGranularityDescription": "One row per user"
  }
}
```

### 2. Column Node (With Quality Metrics, Formats and Examples)

**Cypher**:
```cypher
CREATE (n_2:Column {
  name: "email",
  logicalType: "string",
  format: "yyyy-MM-ddTHH:mm:ssZ",
  is_pii: true,
  is_primary_key: false,
  businessName: "User Email Address",
  examples: "[\"2024-03-10T14:22:35Z\", \"2024-03-11T10:00:00Z\"]",
  quality: "[{\"id\": \"email_valid_format\", \"metric\": \"invalidValues\", \"arguments\": {\"pattern\": \"^.+@.+$\"}, \"mustBe\": 0}]",
  classification: "pii",
  id: "users.email"
})
```

**JSON**:
```json
{
  "id": 2,
  "original_id": "users.email",
  "type": "Column",
  "properties": {
    "name": "email",
    "logicalType": "string",
    "format": "yyyy-MM-ddTHH:mm:ssZ",
    "is_pii": true,
    "is_primary_key": false,
    "businessName": "User Email Address",
    "examples": [
      "2024-03-10T14:22:35Z",
      "2024-03-11T10:00:00Z"
    ],
    "quality": [
      {
        "id": "email_valid_format",
        "metric": "invalidValues",
        "arguments": {
          "pattern": "^.+@.+$"
        },
        "mustBe": 0
      }
    ],
    "classification": "pii"
  }
}
```

### 3. Property-level Relationship Edge

(Notice the implicit `source_columns` is accurately inferred from the bounded property and packaged into a JSON array along with `target_columns`. `provenance` defaults to DDL.)

**Cypher**:
```cypher
CREATE (n_5)-[:PLACED_BY {source_columns: "[\"customer_id\"]", target_columns: "[\"id\"]", provenance: "DDL"}]->(n_0)
```

**JSON**:
```json
{
  "source": 5,
  "target": 0,
  "type": "PLACED_BY",
  "properties": {
    "source_columns": "[\"customer_id\"]",
    "target_columns": "[\"id\"]",
    "provenance": "DDL"
  }
}
```

### 4. Schema-level Composite Key Edge

(Utilizes arrays mapping multi-column relationships. Notice table prefixes are stripped to maintain pure column arrays)

**Cypher**:
```cypher
CREATE (n_20)-[:COMPLEX_JUNCTION {
  source_columns: "[\"order_id\", \"product_id\"]",
  target_columns: "[\"order_id\", \"product_id\"]",
  provenance: "DDL"
}]->(n_9)
```

**JSON**:
```json
{
  "source": 20,
  "target": 9,
  "type": "COMPLEX_JUNCTION",
  "properties": {
    "source_columns": "[\"order_id\", \"product_id\"]",
    "target_columns": "[\"order_id\", \"product_id\"]",
    "provenance": "DDL"
  }
}
```

### 5. LLM Inferred Junction Table Collapsed Edge

(The junction mapping edge absorbs schema properties of the omitted table entity and surfaces provenance/confidence)

**Cypher**:
```cypher
CREATE (n_25)-[:PURCHASED {
  source_columns: "[\"source_user_id\"]",
  target_columns: "[\"id\"]",
  name: "user_products_junction",
  provenance: "LLM_INFERRED",
  confidence: 0.85
}]->(n_0)
```

**JSON**:
```json
{
  "source": 25,
  "target": 0,
  "type": "PURCHASED",
  "properties": {
    "source_columns": "[\"source_user_id\"]",
    "target_columns": "[\"id\"]",
    "name": "user_products_junction",
    "provenance": "LLM_INFERRED",
    "confidence": 0.85
  }
}
```
