# SemaPact Architecture

## Purpose

SemaPact is an ODCS-first contract governance platform.

The current implementation focuses on:

- canonical main contracts
- user-scoped drafts
- lifecycle governance analysis
- contract quality export
- deployment artifact export
- CLI and automation interfaces

SemaPact is not a CRUD system. It is a change-driven system:

- edit -> save draft
- analyze -> compare draft vs main
- promote -> future GitOps workflow

## Current Runtime Layers

### 1. Core

Location:

- `semapact/core/`

Responsibilities:

- load canonical ODCS contracts from supported storage
- validate ODCS contracts and quality rules
- normalize user drafts so business edits do not overwrite technical fields

Key modules:

- `semapact/core/loader.py`
- `semapact/core/validator.py`
- `semapact/core/draft_normalizer.py`

### 2. Lifecycle Governance

Location:

- `semapact/lifecycle/`

Responsibilities:

- analyze main vs source contract changes
- detect breaking changes
- determine auto-deprecations
- apply lifecycle-aware merges

Key modules:

- `semapact/lifecycle/merge_engine.py`
- `semapact/lifecycle/policy.py`

### 3. Utilities

Location:

- `semapact/utils/`

Responsibilities:

- YAML file IO
- YAML string parse/dump through ODCS model definitions
- input normalization helpers

Key modules:

- `semapact/utils/yaml_utils.py`
- `semapact/utils/schema_utils.py`

### 4. Service Layer

Location:

- `semapact/services/`

Responsibilities:

- serve as the interface-independent application boundary into system logic
- normalize interface request values into explicit domain inputs
- own workflow-scoped governance context construction
- delegate merge, lifecycle, validation, and governance rules to their owning layers

Key module:

- `semapact/services/governance_service.py`

Important boundary:

- CLI/UI/API may collect an `effective_date` request value
- `GovernanceService` creates `ChangeContext`
- lifecycle/governance lower layers consume that context and must not regenerate it

### 5. Runtime Observation

Location:

- `semapact/runtime/`

Responsibilities:

- represent point-in-time external runtime state independently from governed contracts
- observe platform-local assets without creating or mutating ODCS contracts
- preserve runtime-only metadata and evidence for later assurance/reconciliation

Key modules:

- `semapact/runtime/models.py`
- `semapact/runtime/unity.py`

Important boundary:

- observed runtime state is read-side evidence, not governed truth
- runtime asset identity is platform-local and distinct from ODCS contract identity
- observation must not invoke lifecycle merge, governance evaluation, release mutation, or platform writeback
- explicit contract import remains a separate workflow

### 6. Exporters

Location:

- `semapact/exporters/`
- `semapact/quality/`

Responsibilities:

- generate Great Expectations suites from ODCS contracts
- generate SQL deployment DDL
- add limited Databricks-specific constraint enhancement where supported

Key modules:

- `semapact/quality/ge_exporter.py`
- `semapact/exporters/sql_exporter.py`

### 7. Orchestration

Location:

- `semapact/orchestrator/`

Responsibilities:

- coordinate non-interactive automation flows
- import -> merge -> validate -> export

Key module:

- `semapact/orchestrator/pipeline.py`

### 8. Interfaces

Location:

- `semapact/interfaces/`

Responsibilities:

- presentation/input adaptation only
- collect user or automation inputs
- display governance results
- call service/application boundaries

Current interface:

- CLI in `semapact/interfaces/cli.py`
- command adapters in `semapact/interfaces/commands/`

## Governed Contract Model

SemaPact assumes:

- Open Data Contract Standard (ODCS) is the single canonical representation of governed desired contract state
- `open_data_contract_standard.model.OpenDataContractStandard` is the canonical governed contract domain model

The system may temporarily work with Python `dict` objects at contract boundaries, but contract normalization should converge back to ODCS objects or ODCS-shaped mappings.

Runtime observations are intentionally different. `ObservedContractState` is a non-canonical read-side model describing what an external platform reports at a point in time. It must not replace or mutate the governed ODCS contract.

Conceptually:

```text
Approved ODCS Contract
= desired governed state

ObservedContractState
= observed runtime state
```

Converting external metadata into a new ODCS contract is an explicit import workflow. Observing runtime state does not implicitly perform that conversion.

## Root Contract Governance

At the top level of the contract, SemaPact currently treats these fields specially:

- `id`
  - immutable once the governed/main contract exists
  - importer-generated IDs are only used when a contract is first created outside SemaPact
- `version`
  - release-managed
  - must not change in the normal import/merge pipeline
  - technical source versions such as Delta table versions must not overwrite the governed contract version

Current behavior:

- `semapact.lifecycle.merge_engine` preserves governed `id` and `version`
- `semapact.lifecycle.policy` flags root `id` changes as `id_violation`
- `semapact.lifecycle.policy` flags root version changes as `version_violation`
- `semapact.orchestrator.pipeline` blocks on `id_violation` and `version_violation`

This means SemaPact currently supports:

- technical schema refresh through import/merge
- governed metadata preservation

It does not yet implement:

- automatic discovery of which contracts in a repo should be released together
- automatic git-tag lookup inside core/service layers

## Release Governance Direction

Current release-version governance is intentionally **per contract**, not per repo.

This supports both:

- one-contract-per-repo setups
- centralized repos containing many governed contracts

Current intended flow:

1. `feature -> main`
   - validate and analyze one changed contract
   - compute `required_bump` for that contract
   - do **not** change contract `version`
2. `main -> release`
   - re-evaluate the release candidate for that contract
   - apply an explicit `release_tag`
   - update contract `version` through the release path only

Current bump rules:

- `none`
  - descriptive-only metadata changes
- `minor`
  - additive or non-breaking structural changes
  - newly introduced schema/property deprecations
- `major`
  - lifecycle-breaking changes

Suggested next release versions are always computed from the last released
contract version and the highest currently required bump. They are not
calculated by chaining unreleased changes together.

Example:

- last released version: `1.2.0`
- unreleased changes: one breaking removal, then one additive field
- final `required_bump`: `major`
- suggested next version: `2.0.0`

If the final `required_bump` is `none`, the suggested version remains the same
as the last released version. In that case, repo-level batch release manifest
generation skips the contract by default.

Current release tooling:

- `semapact release classify`
  - compute `required_bump` for one contract
- `semapact release prepare`
  - prepare one promoted contract candidate with an explicit `release_tag`
- `semapact release create-pr`
  - create one release PR for one contract

## Repo-Level Release Orchestration

Some repositories contain multiple governed contracts. SemaPact supports
repo-level release orchestration helpers, but these helpers do **not** change
the versioning unit.

Current repo-level commands:

- `semapact release classify-repo`
  - compare two contract roots
  - report per-contract statuses such as `changed`, `unchanged`, `added`, and `removed`
  - report `required_bump` for changed contracts only
- `semapact release build-manifest`
  - generate an editable JSON array of per-contract release tasks
  - suggest release tags and source branches from each contract's current version and `required_bump`
- `semapact release create-prs`
  - consume an explicit batch manifest
  - run independent per-contract release preparation and PR creation

Important rule:

- the repository is a batching boundary only
- each contract still owns its own identity, version, release tag, and release decision

Recommended repo-level flow:

1. `semapact release classify-repo`
   - inspect changed contracts
2. `semapact release build-manifest`
   - generate an editable per-contract release task list
3. review and adjust the manifest
   - especially release tags and branch names
4. `semapact release create-prs`
   - create one PR per contract release task

## CI Build Modes

Recommended CI interpretation:

1. `pr`
   - run validation and change classification
   - do not change `contract.version`
   - do not create release PRs
2. `merge`
   - re-run validation on the merged main state
   - keep `contract.version` unchanged
   - publish audit or summary artifacts if needed
3. `release`
   - build or review a per-contract release manifest
   - apply explicit release tags only for contracts that require a bump
   - create release PRs per contract

## Draft Workflow

Current draft workflow:

1. load main contract
2. load existing draft or initialize draft from main
3. edit draft
4. analyze draft vs main
5. save draft
6. promote later through GitOps workflow

Important rules:

- UI must not overwrite the main contract
- draft persists independently
- service layer validates before saving draft
- service layer preserves non-editable contract/schema/property fields from the main contract

Draft storage:

- `.semapact/drafts/{user}/{contract_id}.yaml`

## Storage Support

Current canonical contract roots support:

- local filesystem paths
- ADLS2 paths
- Databricks Unity Catalog mounted volume paths

ADLS2 authentication currently supports:

- `SEMAPACT_ADLS_BEARER_TOKEN`
- `azure.identity.DefaultAzureCredential`

SAS URL authentication is intentionally not supported.

## Quality and Export Boundaries

### Contract validation

`semapact/core/validator.py` validates:

- ODCS structure
- quality rule completeness
- ODCS quality type semantics

### GE export

`semapact/quality/ge_exporter.py`:

- delegates suite generation to datacontract-cli
- performs GE-specific preflight on exported expectation configs
- does not execute runtime validation

### SQL export

`semapact/exporters/sql_exporter.py`:

- delegates base SQL generation to datacontract-cli
- appends Databricks-only constraints for a limited supported subset of ODCS quality rules

Current supported Databricks mappings:

- `nullValues mustBe 0` -> `SET NOT NULL`
- `invalidValues + validValues` -> `CHECK IN (...)`
- `invalidValues + pattern` -> `CHECK RLIKE ...`

Precedence:

- schema `required=True` is emitted first by datacontract-cli as `NOT NULL`
- SemaPact does not emit duplicate nullability constraints

## Current Design Principles

- main governed contract is canonical and immutable from presentation paths
- ODCS is the canonical model for governed desired contract state
- runtime observation is separate read-side evidence and cannot become governed truth implicitly
- service layer is the application boundary between interfaces and system logic
- lifecycle logic belongs in the lifecycle layer
- datacontract-cli is reused where possible instead of reimplemented

## Authoritative Governance Invariants

1. **Centralized Gate Enforcement**: All mutation-capable application paths must obtain an authoritative `GovernanceDecision` and enforce the appropriate `GovernanceOperation` gate before persistence, Git mutation, publication, deployment, or draft submission.
2. **Universal Retired Immutability**: A contract whose effective lifecycle is `retired` is permanently frozen. Any semantic mutation against a retired base contract produces `DecisionResult.BLOCK` with `GovernanceReasonCode.RETIRED_CONTRACT_MODIFIED`. No interface, service, exporter, merge adapter, or future draft implementation may independently reinterpret retired immutability or perform side effects before gate evaluation.
3. **Future Draft Contract**:
   ```text
   Load canonical contract
           ↓
   Create/edit candidate draft
           ↓
   GovernanceService.evaluate(...)
           ↓
   GovernanceOperation.PROPOSE
           ↓
   persist / submit draft
   ```
   If base is `retired` and candidate differs:
   - Evaluator emits `DecisionResult.BLOCK` (`RETIRED_CONTRACT_MODIFIED`)
   - `PROPOSE` gate rejects draft submission
   - UI read-only styling is UX only; backend governance gate is the single authority.

## Known Next Steps

- separate Unity Catalog discovery, observation, and contract import application workflows
- add stable observed-state fingerprints and reconciliation semantics
- formalize draft promotion flow
- continue reducing interface-specific logic that still lives near command/editor helpers
- keep converging governed contract helper logic toward ODCS model-driven behavior
