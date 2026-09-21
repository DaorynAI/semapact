# SemaPact Lifecycle Governance Semantics

This document defines the canonical lifecycle model and governance scope rules for Open Data Contract Standard (ODCS) contracts.

## Supported lifecycle states

SemaPact recognizes exactly four lifecycle states:

| State | Governance meaning | Breaking checks | Auto-deprecation | Mutability |
|---|---|---|---|---|
| `draft` | Development / non-production | skipped | skipped | free evolution |
| `active` | Production contract | enforced | applied | governed |
| `deprecated` | Marked for decommissioning | skipped | skipped | metadata only |
| `retired` | End of life | skipped | skipped | immutable |

Lifecycle strings are normalized case-insensitively with surrounding whitespace removed. Any value other than `draft`, `active`, `deprecated`, or `retired` is invalid.

## Canonical lifecycle authority

Lifecycle authority depends on entity level.

For the contract root, only the native ODCS `contract.status` field is authoritative. When it is absent, the resolver returns `DRAFT`. An explicitly invalid value is reported by `ContractValidator` and governance fails closed.

For `SchemaObject` and `SchemaProperty` entities, including nested properties/items, SemaPact uses the entity's `customProperties.lifecycleStatus` annotation. Non-standard `schema.status` or `property.status` attributes are not governance authorities.

There is no second contract-root lifecycle representation.

## Declared and effective lifecycle

Declared lifecycle is the status explicitly attached to one schema/property entity through `customProperties.lifecycleStatus`.

Effective lifecycle includes parent governance scope:

```text
contract.status
      ↓
effective contract lifecycle
      ↓
schema declared lifecycle, when contract is ACTIVE
      ↓
property declared lifecycle, when parent is ACTIVE
```

The inactive-ancestor invariant is strict: a child cannot reactivate itself past a `draft`, `deprecated`, or `retired` ancestor.

Resolution rules are therefore:

1. Contract: native `contract.status`, otherwise `DRAFT`.
2. Schema: if the contract is not `ACTIVE`, inherit the contract lifecycle; otherwise use the schema declaration when present, else `ACTIVE`.
3. Property: if its parent is not `ACTIVE`, inherit the parent lifecycle; otherwise use the property declaration when present, else `ACTIVE`.

## Governance participation matrix

| Contract status | Schema declared | Property declared | Effective schema | Effective property | Breaking checks |
|---|---|---|---|---|---|
| `active` | none | none | `active` | `active` | included |
| `active` | `draft` | `active` | `draft` | `draft` | excluded |
| `active` | `deprecated` | `active` | `deprecated` | `deprecated` | excluded |
| `active` | `active` | `draft` | `active` | `draft` | excluded |
| `active` | `active` | `deprecated` | `active` | `deprecated` | excluded |
| `draft` | `active` | `active` | `draft` | `draft` | excluded |
| `deprecated` | `active` | `active` | `deprecated` | `deprecated` | excluded |
| `retired` | `active` | `active` | `retired` | `retired` | excluded |

## Fail-closed validation

Lifecycle resolvers are total so deterministic analysis can continue, while `ContractValidator` is the validity authority.

- `normalize_status()` raises on unsupported values.
- `resolve_contract_lifecycle()` returns `DRAFT` when root status is absent or invalid.
- schema/property declared-status resolution returns `None` when no valid declaration exists.
- `ContractValidator` reports malformed lifecycle values.
- `evaluate_governance_decision()` turns validation failure into `DecisionResult.BLOCK`.

This separation prevents malformed input from crashing analysis without treating it as valid governed state.

## Retired contract immutability

`RETIRED` is terminal.

```text
base lifecycle == RETIRED
AND
base contract != candidate contract
        ↓
RETIRED_CONTRACT_MODIFIED
        ↓
DecisionResult.BLOCK
```

This applies to technical schema, business metadata, lifecycle annotations, quality rules, relationships, root status, version, and descriptive changes.

Transitioning an existing non-retired contract into `retired` is a reviewable transition. Reactivating a retired contract is blocked. An unchanged retired contract remains readable and analyzable.

## Operation boundaries

Read-only loading, analysis, classification, and export remain available when a decision is `BLOCK`; they report the decision rather than mutating state.

Mutation-capable paths consume that decision at their canonical boundary:

| Boundary | Canonical entry point | Authority |
|---|---|---|
| governed merge/import | merge/import application workflow | governance PROPOSE gate |
| formal release | `semapact release assess → approve (REVIEW only) → finalize` | PUBLISH approval + exact ReleaseBundle |
| candidate deployment | `semapact deployment assess → deploy` | governance provenance + protected runtime execution context |
| finalized release deployment | `ContractRelease → deployment assess → deploy` | exact release provenance + protected runtime execution context |

A `ContractRelease` never grants runtime execution permission.
