# GovernanceDecision JSON Contract v1

SemaPact exposes governance decisions to external consumers through a versioned JSON contract. The public contract is intentionally separate from the internal Python/Pydantic `GovernanceDecision` model.

Consumers such as CI pipelines, SDKs, MCP servers, agents, and applications must depend on this document and the V1 serializer, not on `GovernanceDecision.model_dump()`.

## Versioning

Every payload contains:

```json
{"schemaVersion":"1"}
```

`schemaVersion` versions the wire schema, not the SemaPact package. An incompatible wire change requires a new schema version.

Within V1, SemaPact treats these as stable:

- public field names;
- enum values;
- governance reason codes and their machine meaning;
- required/optional field presence;
- null versus empty-list behavior;
- canonical list ordering;
- canonical JSON encoding.

Internal governance models may add, remove, or rename implementation fields without changing V1 output.

## Top-level shape

V1 always emits these fields in this order:

1. `schemaVersion`
2. `decisionId`
3. `decision`
4. `contractId`
5. `effectiveDate`
6. `breaking`
7. `requiredVersionBump`
8. `reasonCodes`
9. `reasons`
10. `changes`
11. `validation`
12. `policy`
13. `evidence`

The authoritative serializer is `semapact.governance.governance_decision_to_json()` / `governance_decision_to_dict()`.

## Stable values

`decision`:

- `ALLOW`
- `REVIEW`
- `BLOCK`

`requiredVersionBump`:

- `none`
- `minor`
- `major`

Reason codes use the public `GovernanceReasonCode` vocabulary. Consumers should branch on reason codes, not human-readable messages.

## Reasons

A reason is serialized as:

```json
{
  "code": "PROPERTY_REMOVED",
  "severity": "WARNING",
  "path": "schema[orders].properties[legacy_id]",
  "message": "Property was removed."
}
```

Internal free-form `GovernanceReason.details` is deliberately excluded from V1 because untyped implementation details are not a stable public contract.

`reasonCodes` is a deterministic, de-duplicated convenience list derived from decision reasons.

## Changes

Canonical changes from Issue #82 are exposed directly as the stable explanation of what changed:

```json
{
  "changeType": "REMOVE",
  "entityType": "PROPERTY",
  "identity": ["orders", "legacy_id"],
  "path": "schema[orders].properties[legacy_id]",
  "field": null,
  "before": {"name": "legacy_id"},
  "after": null,
  "domain": "STRUCTURE",
  "breaking": true,
  "reasonCodes": ["PROPERTY_REMOVED"],
  "evidence": []
}
```

Legacy internal `PolicyOutcome.breaking_changes` is not part of V1. Breaking semantics are represented by `changes[].breaking` and `changes[].reasonCodes`.

## Validation, policy, and evidence

Validation exposes stable validity, issue codes, and structured issues:

```json
{
  "valid": false,
  "issueCodes": ["VALIDATION_FAILED"],
  "issues": []
}
```

Policy exposes only stable decision-relevant flags:

```json
{
  "valid": false,
  "idViolation": false,
  "versionViolation": false,
  "retiredViolation": false
}
```

Decision evidence is:

```json
{
  "hasChanges": true,
  "mergeConflictsCount": 0
}
```

## Null and collection rules

- Structural fields are always present.
- Optional scalar/object values use JSON `null`; they are not omitted.
- Collections are always JSON arrays and use `[]` when empty.
- `validation`, `policy`, and `evidence` are always present.
- Python tuples, Enum reprs, Pydantic model reprs, and class names never appear in the wire payload.

## Determinism

`governance_decision_to_json()` emits canonical compact JSON with UTF-8 text semantics and exactly one trailing newline.

Deterministic ordering is enforced for:

- decision reason codes;
- reasons;
- canonical governance changes;
- change reason codes;
- change evidence;
- nested JSON object keys in `before` and `after`.

The same fixed governance inputs therefore produce byte-equivalent V1 JSON.

## CI manifest integration

The existing CI manifest envelope is not versioned by Issue #83. Its `governanceDecision` field now contains the V1 public payload:

```json
{
  "governanceDecision": {
    "schemaVersion": "1"
  }
}
```

Other manifest fields remain an independent artifact contract.

## Out of scope

V1 does not define:

- CLI process exit codes (Issue #84);
- REST or HTTP semantics;
- persistence/audit storage;
- protobuf;
- hosted-service APIs.
