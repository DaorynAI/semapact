# CHANGELOG

<!-- version list -->

## 0.2.0 — ContractOps and Databricks runtime convergence

### Added

- **ContractOps release lifecycle:** deterministic governance analysis, ChangeSet, ReleasePlan, VersionResolution, immutable release bundles, exact REVIEW approval, and finalized ContractRelease artifacts.
- **Runtime reconciliation:** contract-first provider-neutral observation, stable drift reason codes, and explicit IN_SYNC / DRIFT / INDETERMINATE outcomes.
- **Guarded Databricks deployment:** desired-state plans, fresh runtime preview, CREATE / additive ALTER / NO_OP transitions, exact authorization, stale-state checks, execution, and fresh verification.
- **Governance history:** immutable contract-revision identity, release and approval records, and independent optional SQLite/Delta operational telemetry.
- **Unity Catalog integration:** read-side governance and lineage evidence, idempotent release provenance tags, configured SDK authentication composition, and schema-level ODCS data-product import with aggregated relationships.
- **CI/CD examples:** centralized contract repository and per-data-product workflows with content-addressed release and deployment bundle handoffs.
- **Readiness checks:** Databricks deployment doctor and an opt-in protected live-workspace smoke test.

### Changed

- The released ODCS contract remains the authoritative desired state. Generated DDL is a runtime-specific derived operation, not a separate release authority.
- Formal contract release and target-specific runtime deployment are separate lifecycles. Candidate deployments do not create formal versions or release provenance.
- Deployment transition comparison and orchestration are centralized behind provider-neutral schema and runtime interfaces.

### Breaking changes / migration

- Superseded compatibility commands, package aliases, release/deployment workflows, and artifact formats were removed as part of the canonical-only architecture. Do not reuse pre-0.2 release/deployment artifacts.
- Use `semapact release assess`, `release approve` (when REVIEW is required), and `release finalize` for formal contract release; use `semapact deployment assess` and `deployment deploy` for runtime deployment.
- `release classify` and `release plan` are read-only operations and no longer accept `--effective-date`. The option remains available where lifecycle mutation requires it.
- Canonical release/deployment bundles, deployment plans, and operational event schemas begin at schema version 1. Recreate deployment bundles from the exact current contract or finalized ContractRelease.
- Git governance history is not an operational deployment event store; configure optional SQLite or Delta history explicitly if required.

### Links

- [Changes since semapact-v0.1.1](https://github.com/DaorynAI/semapact/compare/semapact-v0.1.1...main)
- [ContractOps release documentation](docs/contractops_phases.md)
- [Deployment plans](docs/deployment_plans.md)
- [Live Databricks smoke procedure](docs/live_databricks_smoke.md)
