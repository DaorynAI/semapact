---
name: devops-workflow
description: Defines current GitOps delivery rules for governed contract changes, pull requests, CI/CD, and versioning.
---

# DevOps Workflow

SemaPact uses GitOps boundaries for governed contract delivery.

------------------------------------------------
CURRENT FLOW

Analyze / Plan
  ↓
Explicit Git workflow
  ↓
PR
  ↓
CI/CD
  ↓
Merge
  ↓
Release

------------------------------------------------
RULES

- MAIN contract is updated only through a reviewed merge path.
- CI/CD validates contracts before merge.
- `required_bump` is computed PER CONTRACT, not per repo.
- feature -> main classification does NOT directly change contract version.
- release version changes occur only through an explicit release path.
- repo-level automation may batch many contracts, but it must orchestrate them as independent per-contract release units.
- multi-contract release automation uses an explicit manifest because each contract may carry its own release tag/version.
- the supported compatibility repo flow is `classify-repo -> build-manifest -> create-prs`.
- suggested release versions are computed from the last released contract version and the highest current bump requirement, not by chaining unreleased bumps.
- if `required_bump` is `none`, the contract is not version-bumped by default and is skipped in batch release manifests unless explicitly selected.

------------------------------------------------
AUTOMATION BOUNDARIES

Feature -> Main:

- run `release classify` for analysis-only classification where that compatibility workflow is used;
- run `release classify-repo` for repo-level compatibility classification;
- do not change `contract.version` during classification.

Canonical release planning:

- use `release plan` to produce the exact `GovernanceDecision`, `ChangeSet`, `ReleasePlan`, and `VersionResolution` artifacts;
- bind planning to explicit base/candidate revision references;
- do not reinterpret governance or version policy in CI scripts.

Compatibility release workflow:

- `release build-manifest` produces explicit per-contract release tasks;
- `release create-prs` consumes those tasks and creates independent release PRs;
- compatibility helpers must not become a second ContractOps implementation.

Merge Build:

- re-run validation/classification when required by the workflow;
- publish only supported summaries or artifacts;
- keep `contract.version` unchanged outside the explicit release path.

------------------------------------------------
FORBIDDEN

- direct writes to main branch;
- bypassing CI/CD or governance authorization;
- embedding lifecycle/version policy inside CI scripts;
- treating repo-level batching as a shared contract-version authority.

------------------------------------------------
GOAL

Ensure safe, auditable, deterministic contract delivery while keeping Git/CI orchestration separate from domain policy.
