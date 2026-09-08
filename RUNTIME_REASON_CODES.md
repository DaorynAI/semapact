# Runtime Reconciliation Reason Codes

SemaPact exposes stable machine-readable reason codes for supported governed-desired-state versus observed-runtime differences.

These codes belong to the **M1 runtime reconciliation read side**. They are a thin semantic projection of raw reconciliation evidence and remain intentionally separate from `GovernanceReasonCode`, which belongs to governance policy and change decisions.

Automation may depend on `reason_code` together with the existing raw evidence fields such as `path`, `expected`, and `observed`.

## Current supported codes

| Reason code | Meaning |
| --- | --- |
| `RUNTIME_SCHEMA_ADDED` | Runtime contains an asset that is not present in the governed contract. |
| `RUNTIME_SCHEMA_REMOVED` | A governed asset is missing from runtime. |
| `RUNTIME_PROPERTY_ADDED` | Runtime contains a property that is not present in the governed contract. |
| `RUNTIME_PROPERTY_REMOVED` | A governed property is missing from runtime. |
| `RUNTIME_PHYSICAL_TYPE_CHANGED` | Runtime physical type differs from the governed physical type. |
| `RUNTIME_REQUIRED_CHANGED` | Runtime nullability differs from the governed required/nullability state. |

## Difference payload

A reconciliation difference keeps the existing raw evidence and adds one stable semantic identifier:

```json
{
  "difference_type": "mismatch",
  "subject": "physical_type",
  "reason_code": "RUNTIME_PHYSICAL_TYPE_CHANGED",
  "path": "schema[orders].properties[id].physicalType",
  "asset_identity": "orders",
  "property_identity": "id",
  "expected": "BIGINT",
  "observed": "STRING"
}
```

`reason_code` does not replace the raw comparison fields. It gives external consumers a stable semantic name without forcing them to depend on the reconciliation engine's internal `(difference_type, subject)` combination.

## Stability rules

- A supported raw runtime difference maps to one stable reason code.
- Existing raw evidence remains authoritative for comparison details and deterministic ordering.
- Runtime reason codes do not determine `ALLOW`, `BLOCK`, or `REVIEW` and do not imply drift causality such as an unauthorized edit or pending deployment.
- Presentation messages and higher-level classifications are intentionally outside this contract.

## Future evidence

Comments, tags, owners, logical-type evidence, constraints, relationships, and lineage are not part of the current minimal observed-state comparison contract. Add reason codes for them only when those evidence types are actually observable and reconciled.
