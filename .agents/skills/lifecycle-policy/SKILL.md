---
name: lifecycle-policy
description: Defines lifecycle governance rules including breaking changes, deprecation, merge constraints, and version enforcement for ODCS contracts.
---
# SemaPact – Lifecycle Governance Policy (ODCS Contracts)
This policy is the SINGLE SOURCE OF TRUTH for all lifecycle and breaking change rules.

Other skills MUST NOT redefine these rules.
They may only reference this policy.
---

## 1. Purpose

This policy defines **lifecycle-aware governance rules** for ODCS contracts within SemaPact.

It ensures:

- Deterministic contract merges  
- Controlled evolution of production contracts  
- Explicit handling of breaking changes  
- Automatic deprecation behavior  
- Clear state-based governance enforcement  

This policy is enforced by:

- **Lifecycle Policy Engine** (governance rules)
- **Merge Engine** (deterministic structural merge)
- **Version Validator** (version bump enforcement)

---

# 2. Lifecycle Model

## 2.1 Supported Lifecycle States

Lifecycle state may exist at:

- Contract level  
- SchemaObject level  
- SchemaProperty level  

Allowed states:
- draft
- active
- deprecated
- retired


### State Semantics

| State | Meaning |
|-------|----------|
| draft | Under development. Not production. |
| active | Production contract. Strict governance applies. |
| deprecated | Still present but marked for removal. |
| retired | End-of-life. Frozen and immutable. |

---

## 2.2 Lifecycle Resolution Order

Lifecycle status is resolved in the following order:

1. `contract.status` (if present)
2. `customProperties.lifecycleStatus`
3. Default = `"draft"`

This applies consistently to:

- Contract
- SchemaObject
- SchemaProperty

---

# 3. Contract-Level Governance

## 3.1 Contract Status Gating

| Contract Status | Breaking Checks | Auto-Deprecation | Merge Allowed |
|-----------------|----------------|-----------------|---------------|
| active          | ✅ Enforced     | ✅ Enforced      | ✅ Allowed (governed) |
| draft           | ❌ Skipped      | ❌ Skipped       | ✅ Free evolution |
| deprecated      | ❌ Skipped      | ❌ Skipped       | ⚠ Metadata-only |
| retired         | ❌ Skipped      | ❌ Skipped       | ❌ Forbidden (frozen) |

---

## 3.2 Retired Contract Rule

A contract in `retired` state:

- MUST NOT be structurally modified
- MUST NOT accept merge operations
- Is considered immutable
- Can only be archived

Attempting to merge into a retired contract MUST raise a governance error.

---

# 4. Schema & Property Lifecycle Behavior

## 4.1 Lifecycle Enforcement Scope

Breaking checks apply ONLY when:

1. Contract is `active`
2. SchemaObject lifecycle ≠ `draft` and ≠ `deprecated`
3. SchemaProperty lifecycle ≠ `deprecated`

---

## 4.2 Behavior Matrix

| Lifecycle State | Breaking Checks | Auto-Deprecation | Structural Changes | Metadata Updates |
|-----------------|----------------|-----------------|-------------------|------------------|
| draft           | ❌ Skip        | ❌ Skip         | ✅ Allowed         | ✅ Allowed |
| active          | ✅ Enforce     | ✅ Apply        | ⚠ Governed        | ✅ Allowed |
| deprecated      | ❌ Skip        | ❌ Skip         | ❌ Forbidden       | ✅ Allowed |
| retired         | ❌ Skip        | ❌ Skip         | ❌ Forbidden       | ❌ Forbidden |

---

## 4.3 Deprecated Field Rules

Deprecated fields:

- Are excluded from breaking change checks
- MUST NOT have structural attributes modified
- MUST retain lifecycleStatus = "deprecated"

Forbidden structural updates:

- logicalType
- physicalType
- precision / scale
- required
- primaryKey
- unique

Allowed updates:

- description
- tags
- additional customProperties (must preserve deprecated status)

Deprecated fields MUST NOT be implicitly reactivated.

---

# 5. Breaking Change Rules

Breaking checks apply ONLY when contract is `active`.

A change is considered **breaking** if:

- Logical type mismatch
- Physical type change
- Decimal precision reduction
- Decimal scale reduction
- Required tightening (`optional → required`)

Version governance derived from lifecycle policy:

- breaking changes require a **major** version bump
- newly introduced schema/property deprecations require a **minor** version bump
- descriptive-only changes require **no required bump**
- bump calculation is **per contract**, not per repo

---

## 5.1 Decimal Rules

Allowed:
- decimal(10,2) → decimal(12,2) (precision widening)
- decimal(10,2) → decimal(10,3) (scale widening)

Breaking:
- decimal(10,2) → decimal(8,2) (precision reduction)
- decimal(10,2) → decimal(10,1) (scale reduction)


---

## 5.2 Allowed Non-Breaking Changes

- Adding new optional fields
- Decimal widening
- Adding new schema objects
- Metadata updates (description, tags)

---

# 6. Auto Deprecation Rules

Auto-deprecation applies ONLY when contract is `active`.

---

## 6.1 Property Auto-Deprecation

If a property:

- Exists in target (current contract)
- Is missing in source (newly generated contract)

Then:

1. Set `customProperties.lifecycleStatus = "deprecated"`
2. Add `deprecationDate` (UTC ISO date)
3. Add tag `"deprecated"` if not present

If already deprecated → no change.

---

## 6.2 SchemaObject Auto-Deprecation

If a schema object:

- Exists in target
- Is missing in source

Then:

1. Mark schema lifecycleStatus = "deprecated"
2. Add `deprecationDate`
3. Preserve properties

Schema objects MUST NOT be physically removed in active contracts.

---

# 7. Merge Update Rules

## 7.1 Matching Properties (Non-Deprecated)

Overwrite the following fields if provided:

- physicalType
- logicalTypeOptions
- partition info
- description
- required
- primaryKey
- unique
- customProperties (merged by identity)

---

## 7.2 Matching Properties (Deprecated)

For deprecated properties:

- Structural attributes MUST NOT change
- Metadata may update
- lifecycleStatus MUST remain `"deprecated"`

---

# 8. Merge Execution Model

## Phase 1 – Analyze

- Resolve lifecycle states
- Validate retired state
- Detect breaking changes
- Identify properties/schemas for auto-deprecation

If conflicts exist → merge MUST fail.

---

## Phase 2 – Apply

- Apply governed updates
- Append new fields
- Apply deprecations
- Preserve deterministic ordering

---

# 9. Deterministic Ordering Rules

To ensure GitOps compatibility:

- SchemaObjects sorted by identity (name)
- Properties sorted by name
- customProperties sorted by property key
- Quality rules sorted by identity key

Output MUST be deterministic and reproducible.

---

# 10. Version Governance

When breaking change is detected in an `active` contract:

- Merge MUST fail unless version bump is provided
- Version Validator ensures correct semantic version increment

---

# 11. Governance Architecture

- **Merge Engine** → Structural deterministic merge  
- **Lifecycle Policy Engine** → Enforces lifecycle rules  
- **Version Validator** → Enforces semantic version compliance  
- **GitOps Workflow** → Audit trail, PR review, deterministic diff  

---

# 12. Summary

This policy ensures:

- Strict governance for production (`active`) contracts  
- Controlled evolution via auto-deprecation  
- Explicit lifecycle-driven enforcement  
- Deterministic Git-based auditing  
- Clear separation between structure and policy  

SemaPact therefore provides **production-grade lifecycle governance for ODCS contracts**.
