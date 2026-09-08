# Runtime Reconciliation Reason Codes

SemaPact exposes stable machine-readable reason codes for supported governed-desired-state versus observed-runtime differences.

These codes belong to the **M1 runtime reconciliation read side**. They are evidence about observed runtime state and are intentionally separate from `GovernanceReasonCode`, which belongs to governance policy and change decisions.

Automation should depend on `reason_code`, `path`, `expected`, `observed`, and `classification`. Human-readable `message` text may evolve and must not be parsed as an automation contract.

## Current supported codes

| Reason code | Classification | Meaning |
| --- | --- | --- |
| `RUNTIME_SCHEMA_ADDED` | `STRUCTURAL` | Runtime contains an asset that is not present in the governed contract. |
| `RUNTIME_SCHEMA_REMOVED` | `STRUCTURAL` | A governed asset is missing from runtime. |
| `RUNTIME_PROPERTY_ADDED` | `STRUCTURAL` | Runtime contains a property that is not present in the governed contract. |
| `RUNTIME_PROPERTY_REMOVED` | `STRUCTURAL` | A governed property is missing from runtime. |
| `RUNTIME_PHYSICAL_TYPE_CHANGED` | `STRUCTURAL` | Runtime physical type differs from the governed physical type. |
| `RUNTIME_REQUIRED_CHANGED` | `STRUCTURAL` | Runtime nullability differs from the governed required/nullability state. |

## Difference payload

Each supported reconciliation difference exposes:

```json
{
  "reason_code": "RUNTIME_PHYSICAL_TYPE_CHANGED",
  "path": "schema[orders].properties[id].physicalType",
  "expected": "BIGINT",
  "observed": "STRING",
  "classification": "STRUCTURAL",
  "message": "A runtime property's physical type differs from the governed contract. Path: schema[orders].properties[id].physicalType"
}
```

The payload also retains the lower-level `difference_type`, `subject`, and canonical asset/property identities used by the reconciliation engine.

## Stability rules

- A supported semantic runtime difference maps to one stable reason code.
- Difference ordering is deterministic and must not depend on upstream API ordering.
- Human-readable messages are presentation text, not stable identifiers.
- Unknown or unsupported raw difference combinations fail explicitly rather than being silently mapped to an existing code.
- Runtime reason codes do not determine `ALLOW`, `BLOCK`, or `REVIEW` and do not imply drift causality such as an unauthorized edit or pending deployment.

## Future evidence

Comments, tags, owners, logical-type evidence, constraints, relationships, and lineage are not part of the current minimal observed-state comparison contract. Their reason codes should be added only when those evidence types are actually observable and reconciled, rather than reserved as unsupported public behavior.
