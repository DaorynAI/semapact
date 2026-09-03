# SemaPact

**Deterministic lifecycle governance and production assurance for ODCS data contracts.**

SemaPact is an open-source, change-driven governance layer for evolving data products safely. It uses the **Open Data Contract Standard (ODCS)** as its canonical governed representation and keeps lifecycle policy deterministic, reviewable, and platform-neutral.

> **SemaPact is not another metadata catalog or CRUD editor. It governs how data products are allowed to change and verifies how governed desired state compares with observed platform state.**

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
- production state no longer matches the governed desired state.

SemaPact treats these as **governance and assurance problems**, not YAML editing operations.

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

For production assurance:

```text
Governed Desired State
          +
ObservedPlatformState
          ↓
Deterministic Reconciliation
          ↓
Raw Differences
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

### Runtime-aware without becoming platform-owned

Platforms such as Databricks Unity Catalog describe what exists now. SemaPact keeps its governance kernel platform-neutral and consumes normalized observation state for assurance.

### AI can consume governance; AI does not become governance authority

Agents may consume governed contracts, decisions, reason codes, and semantic context. Deterministic governance policy remains authoritative.

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
- centralized governance gates for analyze / propose / apply / publish / CI operations.

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

### Raw reconciliation

SemaPact can deterministically compare a governed ODCS desired-state revision with `ObservedPlatformState` and report factual differences for semantics represented on both sides today:

- missing / unexpected assets;
- missing / unexpected properties;
- physical type mismatch;
- required / nullability mismatch.

Reconciliation answers **what differs**. It does not infer why the difference exists, classify deployment history, or mutate the external platform.

## SemaPact + Databricks Unity Catalog

Unity Catalog and SemaPact solve different parts of the problem.

> **Unity Catalog tells you what exists. SemaPact governs desired-state evolution and compares governed state with observed state.**

```text
Git / ODCS
Governed Desired State
        │
        ▼
   ┌──────────┐
   │ SemaPact │
   └──────────┘
      ▲     │
      │     │ governance / assurance artifacts
      │     ▼
Observed Platform State
      ▲
      │
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

### Databricks integration

```bash
pip install "semapact[databricks]"
```

The Databricks SDK owns authentication-provider selection. SemaPact forwards supported connection hints rather than implementing a separate credential system.

## Optional Dependencies

| Extra | Purpose |
| --- | --- |
| `sql` | SQL parsing and SQL-folder workflows |
| `delta` | Delta table support |
| `databricks` | Databricks / Unity Catalog integration |
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
  core/             # loading, validation, editor / release boundaries
  lifecycle/        # canonical identity, lifecycle and change policy
  governance/       # GovernanceDecision and centralized gate
  services/         # application-facing governance service
  observation/      # platform-neutral observed state + fingerprint
  reconciliation/   # governed desired vs observed comparison
  platforms/        # provider adapters such as Databricks
  importers/        # external metadata → ODCS projection
  exporters/        # SQL / graph and other outputs
  quality/          # quality intent adapters
  interfaces/       # CLI and user-facing boundaries
  devops/           # Git / CI release helpers
```

A central architectural rule is:

> **Platform adapters describe external state. Governance decides what contract evolution means. Reconciliation compares governed desired state with observed state.**

## What SemaPact Does Not Try to Replace

SemaPact is not intended to replace:

- Databricks Unity Catalog or another metadata catalog;
- dbt, Spark, Lakeflow, or another transformation engine;
- Great Expectations or another data-quality execution runtime;
- Terraform / Databricks Asset Bundles as general infrastructure tooling;
- Git review and human authorization processes.

SemaPact provides a deterministic governance and assurance layer around those systems.

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

## Project Direction

The current delivery direction is a governed desired-state control plane:

```text
GOVERN
Can this contract change be allowed?

CONVERGE
Can governed desired state safely become runtime state?

ASSURE
Does observed runtime state match governed desired state?

PROVE
What happened, why, and through which decision / release / deployment / observation?
```

Not every stage above is complete today. The repository keeps these boundaries explicit so later deployment, drift classification, evidence, and audit capabilities can be added without collapsing responsibilities into one layer.

## Open Data Contract Standard

SemaPact uses the **Open Data Contract Standard (ODCS)** as its canonical contract representation rather than introducing a proprietary data-contract schema.

## Contributing

SemaPact is developed in the open. Contributions are welcome, including bug reports, integrations, architecture discussions, governance scenarios, Databricks / Unity Catalog cases, and schema-evolution edge cases.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md) for project guidance.

## License

MIT
