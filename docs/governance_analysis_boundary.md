# Governance Analysis Boundary

SemaPact governance analysis is a pure, repeatable operation. It determines what a proposed contract change means; it does not perform the change or publish anything.

## Canonical Boundary

```text
Analyze
  base + candidate + ChangeContext
        ↓
  GovernanceDecision

Apply
  explicit local/candidate mutation

Publish
  explicit external side effects
```

M0 establishes and protects the analysis boundary. Full ContractOps phase modeling belongs to later milestones.

## Analysis Entry Points

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

Application clients should normally enter governance analysis through:

```python
GovernanceService.evaluate(...)
```

`GovernanceService.merge_and_evaluate(...)` may construct an in-memory merged candidate before evaluation, but it must not persist that candidate or perform external publication side effects.

## Analysis Invariants

Governance analysis must not:

- mutate the base contract;
- mutate the candidate contract;
- write contract, manifest, or other files;
- create or modify Git branches, commits, or tags;
- create pull requests;
- publish metadata or deployment artifacts;
- apply a release version;
- invoke deployment or runtime mutation.

For the same normalized inputs and the same `ChangeContext`, repeated analysis must produce the same deterministic `GovernanceDecision`, including the same `decision_id`.

Analysis may compute evidence such as validation results, canonical `GovernanceChange` values, policy findings, breaking status, and the minimum required version bump. Computing a required version bump is analysis; applying a version is not.

## Side-Effecting Operations

Mutation-capable workflows are downstream consumers of governance analysis. They must consume an already-produced `GovernanceDecision` (or an application result containing that decision) and enforce the appropriate `GovernanceOperation` gate before performing protected side effects.

Conceptually:

```text
GovernanceDecision
        ↓
GovernanceOperation gate
        ↓
explicit Apply / Publish / CI side effect
```

A client or adapter must not independently reinterpret breaking changes, validation, lifecycle policy, or version requirements to bypass the authoritative decision.

## Regression Protection

`tests/test_governance_analysis_boundary.py` protects this architecture contract by checking that:

- the authoritative evaluator does not import integration or mutation layers;
- decision evaluation performs no filesystem or process side effects;
- input contracts remain unchanged;
- repeated evaluation is deterministic;
- the `GovernanceService.evaluate(...)` application boundary preserves the same purity guarantees.
