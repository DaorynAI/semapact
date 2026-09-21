# SemaPact Examples

This folder contains reference assets for wiring SemaPact into CI/CD.

## Pull-request validation

- `ci/pr-check.example.sh`
  - repository-level contract classification for PR validation
- `azure-devops/semapact-pr-validation.yml`
  - the same classification pattern in Azure DevOps

These examples use `semapact release classify-repo` only to discover which governed
contracts changed. They do not create release branches, manifests, version bumps, or
pull requests.

## Canonical GitHub Actions CI/CD

- `github/data-product-ci-cd.yml`
  - end-to-end candidate CI + formal release + production deployment for a standard
    data-product repo
- `github/central-contract-repo-ci-cd.yml`
  - changed-contract discovery, matrix release finalization, immutable artifact handoff,
    target fan-out, and a single governance-ledger write for a central contract repo
- `github/semapact-enrich.yml`
  - on-demand LLM contract enrichment trigger

The two bundle-driven CI/CD examples intentionally use only public SemaPact CLI surfaces
plus ordinary GitHub Actions/Git commands. They are architecture fitness tests: awkward
JSON extraction, internal IDs, Git round-trips, or duplicate approval plumbing indicate
a CLI/application-boundary problem.

Both CI/CD examples assume contracts define Databricks servers named `development` and
`production`; adapt those names to local contract conventions.

Operational deployment history is config-first through `.semapact.yaml`. The examples
do not repeat `--operational-history` on every deployment.

The examples use two distinct GitHub Environment boundaries. `contract-release` supplies
human PUBLISH approval for REVIEW releases, recorded with `semapact release approve`.
`production` protects whether the deployment job may run; SemaPact does not convert a
finalized ContractRelease into DEPLOY authorization.

`release finalize --release-out` publishes the immutable ContractRelease as a pipeline
artifact. Deployment jobs consume that artifact directly with `deployment assess
--release`; Git history remains the governance ledger rather than the job-to-job
transport.
