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

- `github/semapact-enrich.yml`
  - on-demand LLM contract enrichment trigger
- `github/semapact-release.yml`
  - release promotion trigger

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
