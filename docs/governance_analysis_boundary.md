# Governance Analysis Boundary

SemaPact governance analysis is a pure, repeatable operation. It determines what a proposed contract change means; it does not perform the change or publish anything.

## Canonical boundary

```text
base + candidate + ChangeContext
        ↓
GovernanceDecision
        ↓
application workflow
        ↓
explicit mutation / release / deployment boundary
```

Later phases consume the decision rather than recomputing governance semantics.

## Analysis entry points

The authoritative domain evaluator is:

```python
evaluate_governance_decision(
    base_contract,
    candidate_contract,
    *,
    context,
    merge_conflicts=(),
)
```

Application clients normally enter through:

```python
GovernanceService.evaluate(...)
```

`GovernanceService.merge_and_evaluate(...)` may construct an in-memory merged candidate before evaluation, but it must not persist that candidate or perform publication/runtime side effects.

## Analysis invariants

Governance analysis must not:

- mutate the base or candidate contract;
- write contract or artifact files;
- create Git branches, commits, or tags;
- create pull requests;
- publish metadata;
- apply a release version;
- invoke runtime mutation.

For identical normalized inputs and `ChangeContext`, repeated analysis must produce the same deterministic `GovernanceDecision`, including `decision_id`.

Computing validation evidence, canonical `GovernanceChange` values, policy findings, breaking status, and minimum required version bump is analysis. Applying a version or changing runtime state is not.

## Policy findings, decisions, and execution authority

These are distinct:

```text
policy.valid
= whether policy-breaking findings were detected

GovernanceDecision
= authoritative governance disposition

execution authority
= permission to cross a specific side-effect boundary
```

A breaking change may legitimately produce:

```text
policy.valid = false
decision = REVIEW
```

Consumers must use the authoritative `GovernanceDecision` and the workflow boundary that owns the side effect. They must not reinterpret `policy.valid`, `breaking`, or individual reason codes as independent permission checks.

Formal release REVIEW approval is scoped to the exact release artifact. Runtime deployment permission belongs to the protected CI/CD execution context; it is not inferred from `ContractRelease`.

## Regression protection

`tests/test_governance_analysis_boundary.py` protects analysis purity and determinism.

The two canonical GitHub Actions examples are architecture fitness tests for the public workflow boundary:

- `examples/github/data-product-ci-cd.yml`
- `examples/github/central-contract-repo-ci-cd.yml`

They must use public CLI surfaces only. If they require internal artifact reconstruction, duplicate approval logic, unnecessary Git round-trips, or internal implementation IDs, that is treated as an application/CLI boundary defect.
