# SemaPact

**Deterministic lifecycle governance and production assurance for ODCS data contracts.**

SemaPact is an open-source, change-driven governance layer for evolving data products safely. It uses the **Open Data Contract Standard (ODCS)** as its canonical governed representation and keeps lifecycle policy deterministic, reviewable, and platform-neutral.

> **SemaPact is not another metadata catalog or CRUD editor. It governs how data products are allowed to change, turns approved contract releases into explicit deployment intent, and verifies how governed desired state compares with observed platform state.**

## Installation

Install the platform-neutral core:

```bash
pip install semapact
```

For Databricks / Unity Catalog integration:

```bash
pip install "semapact[databricks]"
```

Other integrations are exposed as optional extras so the base package does not require unrelated platform or UI dependencies.

```bash
pip install "semapact[sql]"
pip install "semapact[delta]"
pip install "semapact[quality]"
pip install "semapact[llm]"
pip install "semapact[tui]"
```

Verify the CLI:

```bash
semapact --help
```

## The Problem SemaPact Solves

Validating one contract file is the easy part. Production governance becomes harder when the data product evolves:

- a column disappears;
- a required field becomes optional;
- a physical type changes;
- decimal precision or scale is reduced;
- an active field needs to be deprecated;
- a contract is retired and must become immutable;
- an approved contract release needs to become runtime state safely;
- production state no longer matches the governed desired state.

SemaPact treats these as **governance, convergence, and assurance problems**, not YAML editing operations.

```text
Current Governed Contract
          +
Candidate Contract
          ↓
Canonical Identity
          ↓
Change Analysis
          ↓
Lifecycle + Version Policy
          ↓
GovernanceDecision
          ↓
Governance Gate
```

Canonical ContractOps then carries the exact governed decision forward:

```text
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
→ ContractOpsAuthorization
→ AppliedContractRelease
→ DeploymentPlan
→ DeploymentAuthorization
→ runtime mutation
```

For production assurance:

```text
Governed Desired State
          +
ObservedPlatformState
          ↓
Deterministic Reconciliation
          ↓
IN_SYNC / DRIFT / INDETERMINATE
```

The governed desired state is an authoritative ODCS revision selected by an upstream governance / release / authorization process. `approved` is not an ODCS lifecycle status and reconciliation does not invent one.

## Core Principles

### Change-driven, not CRUD

Governance begins with the difference between a governed base revision and a proposed candidate revision. SemaPact is designed around change analysis rather than directly editing canonical state in place.

### Deterministic by default

The same inputs and governance context should produce the same result. Lifecycle policy belongs in deterministic code, not in UI state or LLM reasoning.

### Canonical identity is explicit

For the current governance model:

```text
schema identity   = lowercase(schema.name)
property identity = lowercase(schema.name) + lowercase(property.name)
```

`physicalName` is not identity.

### Lifecycle and authorization are separate concepts

SemaPact models lifecycle states such as:

```text
DRAFT → ACTIVE → DEPRECATED → RETIRED
```

Lifecycle status does not itself mean that a revision has been authorized for release.

### Side effects are operation-scoped

SemaPact distinguishes analysis and planning from side effects. APPLY, PUBLISH, and DEPLOY are separate protected operations. A publication authorization cannot be reused as runtime deployment authority.

### Runtime-aware without becoming platform-owned

Platforms such as Databricks Unity Catalog describe what exists now. SemaPact keeps its governance kernel and deployment intent provider-neutral, while provider adapters translate supported runtime operations explicitly.

### AI can consume governance; AI does not become governance authority

Agents may consume governed contracts, decisions, reason codes, release/deployment artifacts, and semantic context. Deterministic governance policy remains authoritative.

## Current Capabilities

### Deterministic lifecycle governance

SemaPact currently supports deterministic change analysis and lifecycle-aware policy including:

- canonical schema and property identity;
- active / draft / deprecated / retired lifecycle semantics;
- retired-state immutability;
- active-field removal handling and governed deprecation;
- physical type change detection;
- logical type incompatibility checks;
- decimal precision / scale reduction checks;
- required / nullability tightening;
- relationship change handling;
- version-policy classification;
- deterministic `GovernanceDecision` artifacts;
- centralized governance gates for ANALYZE / PROPOSE / APPLY / PUBLISH / DEPLOY / CI operations.

### Canonical ContractOps release planning

The release planning path evaluates governance once and produces exact deterministic artifacts:

```text
GovernanceDecision
→ ChangeSet
→ ReleasePlan
→ VersionResolution
```

`semapact release plan` requires explicit base and candidate revision references so downstream authorization and application can refer to the exact workflow revisions rather than mutable file paths.

SemaPact supports two version-authority modes:

- `semapact` — independently version contracts from their governed change requirements;
- `git` — validate an explicitly supplied product/repository release version against the governance-required minimum bump.

See [`docs/contractops_phases.md`](docs/contractops_phases.md) and [`docs/version_authority.md`](docs/version_authority.md).

### Governed runtime deployment

`semapact deployment` exposes a canonical CLI/CI surface:

```text
plan
→ DeploymentPlan

preview
→ fresh runtime observation
→ DeploymentPreview

execute
→ exact plan + preview + DeploymentAuthorization
→ provider execution

verify
→ fresh observation + reconciliation
→ IN_SYNC / DRIFT / INDETERMINATE
```

Planning and preview are read-only. Runtime mutation occurs only through `deployment execute`, and provider execution success is not treated as convergence proof.

The first Databricks write capability is intentionally narrow: create a missing managed Delta table, add missing nullable governed columns to an existing managed table, or perform NO_OP when the governed shape is already satisfied. Rename, existing-column type/nullability mutation, required-column addition without a safe migration strategy, DROP, and existing external/non-managed asset mutation fail closed.

See [`docs/deployment_plans.md`](docs/deployment_plans.md).

### Databricks discovery and observation

With the `databricks` extra, SemaPact provides a thin read-side integration using the official Databricks SDK:

```text
Databricks
   ├── Discovery
   │     → asset identities
   │
   └── Observation
         → ObservedPlatformState
```

Discovery identifies assets in a requested scope. Observation captures platform-neutral physical schema state.

### Stable observation fingerprint

Observed physical schema state can be represented by a deterministic fingerprint over the current `obs-v1` semantic payload:

```text
platform
asset identity
asset type
property identity
physical type
nullability
```

Volatile envelope fields such as capture time and source location are excluded from the content fingerprint.

### Runtime reconciliation and convergence verification

SemaPact deterministically compares governed desired state with `ObservedPlatformState` and reports factual differences for semantics represented on both sides today:

- missing / unexpected assets;
- missing / unexpected properties;
- physical type mismatch;
- required / nullability mismatch.

Reconciliation classifies the result as `IN_SYNC`, `DRIFT`, or `INDETERMINATE`. Deployment verification reuses the same reconciliation authority; it does not invent a separate convergence status machine.

See [`docs/runtime_reconciliation.md`](docs/runtime_reconciliation.md).

## SemaPact + Databricks Unity Catalog

Unity Catalog and SemaPact solve different parts of the problem.

> **Unity Catalog tells you what exists. SemaPact governs desired-state evolution, executes explicitly supported governed mutations, and verifies observed state against that governed intent.**

```text
Git / ODCS
Governed Desired State
        │
        ▼
   ┌──────────┐
   │ SemaPact │
   └──────────┘
      │     ▲
      │     │ observation / reconciliation
      ▼     │
Governed runtime mutation
      │     │
      ▼     │
Databricks / Unity Catalog
```

Unity Catalog remains responsible for runtime assets, access control, lineage, metadata, and platform enforcement. SemaPact does not aim to replace it.

## Quick Start

### Inspect the CLI

```bash
pip install semapact
semapact --help
```

### Import from SQL

Install SQL support:

```bash
pip install "semapact[sql]"
```

Then import into ODCS:

```bash
semapact import \
  --format sql-folder \
  --source ./ddl \
  --output ./contracts/orders.yaml
```

### Analyze / merge governed contract evolution

```bash
semapact merge \
  --base ./generated.yaml \
  --business ./contracts/orders.yaml \
  --output ./contracts/orders.merged.yaml \
  --effective-date 2026-09-03
```

### Build canonical release planning artifacts

```bash
semapact release plan \
  --base ./contracts/orders.yaml \
  --candidate ./contracts/orders.candidate.yaml \
  --base-revision-ref git:abc123 \
  --candidate-revision-ref git:def456 \
  --effective-date 2026-09-11
```

The output contains the canonical `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` artifacts.

### Databricks integration

```bash
pip install "semapact[databricks]"
```

The Databricks SDK owns authentication-provider selection. SemaPact forwards supported connection hints rather than implementing a separate credential system.

After an exact `AppliedContractRelease` and deployment authorization have been produced, the runtime path is exposed through:

```bash
semapact deployment plan --help
semapact deployment preview --help
semapact deployment execute --help
semapact deployment verify --help
```

## Optional Dependencies

| Extra | Purpose |
| --- | --- |
| `sql` | SQL parsing and SQL-folder workflows |
| `delta` | Delta table support |
| `databricks` | Databricks / Unity Catalog observation and governed deployment |
| `quality` | Great Expectations integration |
| `graph` | Graph export support |
| `llm` | Optional LLM-assisted semantic enrichment |
| `azure` | ADLS2 access |
| `s3` | Amazon S3 access |
| `tui` | Textual terminal interface |
| `all` | All currently supported optional integrations |

Optional extras are intentionally separate from the base distribution. If an integration is not listed here, it is not part of the supported public extra surface.

## Package Architecture

```text
semapact/
  core/             # loading, validation, compatibility workflow boundaries
  lifecycle/        # canonical identity, lifecycle and change policy
  governance/       # GovernanceDecision and centralized gate
  contractops/      # deterministic release planning / authorization / apply / publish domain
  deployment/       # provider-neutral deployment plans, authorization, preview contracts
  runtime/          # provider-neutral governed runtime asset projection
  services/         # thin application-facing orchestration boundaries
  observation/      # platform-neutral observed state + fingerprint
  reconciliation/   # governed desired vs observed comparison
  platforms/        # provider adapters such as Databricks
  importers/        # external metadata → ODCS projection
  exporters/        # SQL / graph and other outputs
  quality/          # quality intent adapters
  interfaces/       # CLI and user-facing boundaries
  devops/           # Git / CI compatibility helpers
```

A central architectural rule is:

> **Governance decides what contract evolution means. ContractOps carries exact governed artifacts across authorization boundaries. Platform adapters execute only explicitly supported runtime mutations. Reconciliation independently verifies observed state.**

## What SemaPact Does Not Try to Replace

SemaPact is not intended to replace:

- Databricks Unity Catalog or another metadata catalog;
- dbt, Spark, Lakeflow, or another transformation engine;
- Great Expectations or another data-quality execution runtime;
- Terraform / Databricks Asset Bundles as general infrastructure tooling;
- Git review and human authorization processes.

SemaPact provides a deterministic governance, convergence, and assurance layer around those systems.

## Development

Clone the repository and install the development environment with all supported extras:

```bash
uv sync --all-extras --group dev --frozen
```

Run tests:

```bash
uv run pytest
```

Build the Python distribution:

```bash
uv build
```

## Product Model

SemaPact is organized as a governed desired-state control plane:

```text
GOVERN
Can this contract change be allowed?

CONVERGE
Can the exact governed release safely become runtime state?

ASSURE
Does observed runtime state match governed desired state?

PROVE
What happened, why, and through which decision / release / deployment / observation?
```

Governance, release planning, guarded deployment, and runtime reconciliation are implemented as separate boundaries so persistence, history, additional provider capabilities, and audit surfaces can evolve without collapsing these responsibilities into one layer.

## Open Data Contract Standard

SemaPact uses the **Open Data Contract Standard (ODCS)** as its canonical contract representation rather than introducing a proprietary data-contract schema.

## Contributing

SemaPact is developed in the open. Contributions are welcome, including bug reports, integrations, architecture discussions, governance scenarios, Databricks / Unity Catalog cases, and schema-evolution edge cases.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md) for project guidance.

## License

Copyright 2026 Elliot Sun.

Licensed under the Apache License, Version 2.0 (Apache-2.0). See [`LICENSE`](LICENSE).
