# Governance Change Context

SemaPact governance analysis must be reproducible from explicit inputs. Governance-relevant values must not be silently resolved from wall-clock time, environment variables, Git state, or caller-specific process state inside the governance kernel.

## Current context contract

Issue #79 intentionally introduces the smallest context required by current governance semantics:

```python
ChangeContext(
    effective_date=date(2026, 8, 13),
)
```

`effective_date` is required. It has no wall-clock default.

The ownership rule is:

```text
CLI / UI / API request
    effective_date value or override
            ↓
GovernanceService
    creates ChangeContext once
            ↓
merge → governance evaluation → release artifacts
```

Interfaces collect request values; they do not construct the domain `ChangeContext`. The application service owns that construction and lower layers consume the supplied context without regenerating, overwriting, or reinterpreting it.

## Semantic effect

`effective_date` currently affects lifecycle auto-deprecation metadata. When an active schema or property is auto-deprecated and does not already carry `deprecationDate`, SemaPact uses the explicitly supplied effective date.

Existing `deprecationDate` values are preserved. The merge/governance kernel never substitutes `date.today()`, `datetime.now()`, or another process-time value.

The effective date is included in the deterministic governance decision identity and serialized on `GovernanceDecision.context`.

## Application boundary

`semapact.services.GovernanceService` is the application boundary responsible for converting an interface-level effective-date value into `ChangeContext`.

Until a persistent Draft/ChangeSet workflow owns and stores that value, CLI governance operations accept:

```text
--effective-date YYYY-MM-DD
```

This CLI argument is an application request value, not ownership of `ChangeContext`. A future Draft/ChangeSet service may create or select the date once and persist it so users do not need to re-enter it for analyze, re-analyze, CI, and release operations.

Batch release manifests persist the effective date with each task. Later release execution restores the same semantic date instead of resolving a new one at execution time.

## Operational timestamps are separate

Operational audit timestamps such as `AuditMetadata.last_merge_ts` are execution metadata. They may record when an operation happened, but they do not participate in governance decision semantics or `decision_id` generation.

## Environment and release provenance

Credentials, CI workspace paths, Git SHA values, Databricks Bundle release metadata, actor identity, and release/version authority are not currently governance-semantic context fields. They must not be copied into ODCS contracts merely to support governance analysis.

Release/version authority is tracked separately from Issue #79.

## Determinism contract

For the same:

- base ODCS contract
- candidate ODCS contract
- merge conflicts
- `ChangeContext`

SemaPact must produce the same normalized `GovernanceDecision`, including the same decision ID, regardless of execution time.
