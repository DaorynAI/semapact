# SemaPact Lifecycle Governance Semantics

This document describes the authoritative lifecycle model, resolution order, and governance scope rules for Open Data Contracts (ODCS) within SemaPact.

---

## 1. Supported Lifecycle States

SemaPact governance operates on four canonical lifecycle states:

| State | Governance Meaning | Breaking Checks | Auto-Deprecation | Mutability |
|---|---|---|---|---|
| `draft` | Development / non-production. | ❌ Skipped | ❌ Skipped | ✅ Free evolution |
| `active` | Production contract. Strict governance applies. | ✅ Enforced | ✅ Applied | ⚠ Governed |
| `deprecated` | Marked for decommissioning. | ❌ Skipped | ❌ Skipped | ⚠ Metadata only |
| `retired` | End of life / decommissioned. | ❌ Skipped | ❌ Skipped | ❌ Immutable (BLOCK) |

### Read Normalization & Aliases

Lifecycle status strings are normalized case-insensitively with leading/trailing whitespace removed:
- `"draft"` -> `LifecycleStatus.DRAFT`
- `"proposed"` -> `LifecycleStatus.DRAFT`
  > [!NOTE]
  > `"proposed"` is a read-only governance interpretation alias for ODCS compliance; SemaPact does not rewrite ODCS `status: proposed` to `status: draft` in the contract YAML merely during resolution.
- `"active"` -> `LifecycleStatus.ACTIVE`
- `"deprecated"` -> `LifecycleStatus.DEPRECATED`
- `"retired"` -> `LifecycleStatus.RETIRED`

Any unknown or unsupported lifecycle status value is rejected by normalization and flagged by `ContractValidator` as a validation issue.

---

## 2. Canonical Authority & Fallback Order

Authority is defined by entity level:

### Contract Root
1. Native `contract.status` (canonical ODCS root status field)
2. `contract.customProperties.lifecycleStatus` (legacy fallback)
3. Default: `LifecycleStatus.DRAFT`

### SchemaObject & SchemaProperty (including nested `properties[]` and `items`)
1. Entity's own `customProperties.lifecycleStatus` only (canonical ODCS extension point)
2. Note: Non-standard `schema.status` or `property.status` attributes are not governance authorities.

---

## 3. Declared vs. Effective Lifecycle

SemaPact strictly differentiates between **declared lifecycle** and **effective lifecycle**:

### Declared Lifecycle
- The status explicitly annotated on an individual entity (`customProperties.lifecycleStatus`).
- Resolved via `resolve_declared_entity_lifecycle(entity)`.
- Used for release change classification (`_has_new_deprecations`) to determine if an entity was newly marked deprecated.

### Effective Governance Lifecycle
- The status of an entity taking into account parent governance scope and hierarchy.
- Resolved via:
  - `resolve_contract_lifecycle(contract)`
  - `resolve_schema_lifecycle(schema_obj, contract=contract)`
  - `resolve_property_lifecycle(prop, parent_lifecycle=...)`

### Recursive Inheritance Invariant
> [!IMPORTANT]
> **Inactive Ancestor Invariant**: An inactive ancestor (`draft`, `deprecated`, `retired`) places its entire subtree outside active governance scope. A child entity cannot reactivate itself past an inactive parent.

#### Resolution Hierarchy:
1. **Contract**: `contract.status` -> `contract.customProperties.lifecycleStatus` -> `DRAFT`.
2. **Schema**:
   - If `effective contract != ACTIVE` -> parent contract effective status wins.
   - Else if schema has declared `lifecycleStatus` -> schema declared status.
   - Else -> `ACTIVE`.
3. **Property (Top-level or Nested `properties[]` / `items`)**:
   - If `parent_lifecycle != ACTIVE` -> `parent_lifecycle` wins.
   - Else if property has declared `lifecycleStatus` -> property declared status.
   - Else -> `ACTIVE`.

---

## 4. Governance Participation Matrix

| Contract Status | Schema Declared | Property Declared | Effective Schema | Effective Property | Breaking Checks Scope |
|---|---|---|---|---|---|
| `active` | *(none)* | *(none)* | `active` | `active` | ✅ Included |
| `active` | `draft` | `active` | `draft` | `draft` | ❌ Excluded (parent inactive) |
| `active` | `deprecated` | `active` | `deprecated` | `deprecated` | ❌ Excluded (parent inactive) |
| `active` | `active` | `draft` | `active` | `draft` | ❌ Excluded (property draft) |
| `active` | `active` | `deprecated` | `active` | `deprecated` | ❌ Excluded (property deprecated) |
| `draft` | `active` | `active` | `draft` | `draft` | ❌ Excluded (contract draft) |
| `retired` | `active` | `active` | `retired` | `retired` | ❌ Excluded (contract retired) |

---

## 5. Fail-Closed Validation Integration

> [!NOTE]
> **Total Resolvers vs. Validation Authority**:
> Lifecycle resolvers are intentionally total for deterministic analysis; lifecycle validity is enforced by `ContractValidator`.
>
> - `normalize_status()`: Strict parser (`ValueError` on unsupported values).
> - Resolvers (`resolve_contract_lifecycle`, `resolve_schema_lifecycle`, `resolve_property_lifecycle`): Total / tolerant functions with safe fallbacks (`DRAFT` / `None`), preventing crashes in downstream analysis pipelines.
> - `ContractValidator`: Authoritative validity check emitting `ValidationIssue(severity="error")` on invalid lifecycle values.
> - `evaluate_governance_decision()`: Blocks changes with `VALIDATION_FAILED` whenever `ContractValidator` reports issues.

When an unknown or malformed lifecycle status is provided (e.g. `status: "unknown"`):
1. `ContractValidator` detects invalid status and records a `VALIDATION_FAILED` issue.
2. `evaluate_governance_decision()` receives `ValidationOutcome(valid=False)` and emits a deterministic `GovernanceDecision(decision=DecisionResult.BLOCK)`.
3. Evaluation and merge pipelines execute deterministically without leaking unhandled exceptions.

