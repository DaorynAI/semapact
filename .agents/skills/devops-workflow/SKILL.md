---
name: devops-workflow
description: Defines GitOps workflow for contract promotion including branch creation, pull requests, CI/CD, and versioning.
---

# DevOps Workflow

SemaPact follows a GitOps-based promotion model.

------------------------------------------------
FLOW

Draft → Promote → PR → CI/CD → Merge → Release

------------------------------------------------
RULES

- MAIN contract updated only via merge
- CI/CD validates contracts before merge
- `required_bump` is computed PER CONTRACT, not per repo
- feature -> main determines `required_bump` but does NOT change contract version
- release flow applies the explicit version/tag per contract after merge
- repo-level automation may batch many contracts, but it must orchestrate them as independent per-contract release units
- multi-contract release automation should use an explicit manifest because each contract may carry its own release tag/version
- a healthy repo-level flow is: `classify-repo -> build-manifest -> create-prs`
- suggested release versions are always computed from the last released contract version and the highest current bump requirement, not by chaining unreleased bumps
- if `required_bump` is `none`, the contract should not be version-bumped by default and should be skipped in batch release manifests unless a team explicitly chooses otherwise

------------------------------------------------
PREFERRED AUTOMATION

Feature -> Main:

- run `release classify` for single-contract repos
- run `release classify-repo` for multi-contract repos
- fail or warn based on the returned per-contract `required_bump`
- do not change `contract.version`

Main -> Release:

- run `release build-manifest`
- review or edit the generated per-contract manifest
- run `release create-prs`

Merge Build:

- re-run validation and classification on merged main if needed
- publish summaries or audit artifacts
- keep `contract.version` unchanged until release

------------------------------------------------
FUTURE

- auto PR creation
- automated validation pipelines
- audit logs

------------------------------------------------
FORBIDDEN

- direct writes to main branch
- bypassing CI/CD

------------------------------------------------
GOAL

Ensure safe, auditable, and deterministic contract delivery.
