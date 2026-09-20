# SemaPact Examples

This folder contains reference assets for wiring SemaPact into CI/CD.

## Release Assets

- `release/release-manifest.example.json`
  - example per-contract batch release manifest

## CI Shell Examples

- `ci/pr-check.example.sh`
  - single-contract and multi-contract PR build examples
- `ci/release.example.sh`
  - multi-contract release build example

## GitHub Actions Examples

- `github/data-product-ci-cd.yml`
  - end-to-end candidate CI + formal-release CD for a standard data-product repo
- `github/central-contract-repo-ci-cd.yml`
  - changed-contract discovery, matrix assessment/deployment, and single-write governance ledger for a centralised contract repo
- `github/semapact-enrich.yml`
  - on-demand LLM contract enrichment trigger
- `github/semapact-release.yml`
  - legacy release-promotion example

## Azure DevOps Examples

- `azure-devops/semapact-pr-validation.yml`
  - PR validation template
- `azure-devops/semapact-release.yml`
  - release promotion template

Important rules reflected by these examples:

- version governance is per contract, not per repo
- PR builds classify changes but do not bump contract versions
- release builds apply explicit release tags only for contracts that require a bump
- contracts with `required_bump = none` are skipped by default in batch release manifests


## Bundle-driven CI/CD examples

The two bundle-driven GitHub examples intentionally use only public SemaPact CLI surfaces plus ordinary GitHub Actions/Git commands. They are also architecture smoke tests: any large amount of JSON extraction or repository glue is a signal that the CLI boundary may need simplification.

Both examples assume contracts define Databricks servers named `development` and `production`; adapt those names to local contract conventions.

Operational deployment history is config-first through `.semapact.yaml`. The examples do not repeat `--operational-history` on every deployment.

GitHub Environment protection is used as the human production approval surface. Until SemaPact has a provider-native approval-ingestion command, the examples explicitly project a REVIEW bundle into the generic `semapact approval record` CLI before deployment.
