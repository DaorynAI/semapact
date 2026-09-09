# Contract version authority

SemaPact separates governance classification from release version selection.

```text
GovernanceDecision.requiredVersionBump
        ↓
ReleasePlan
        +
current released ODCS version
        +
version-authority configuration
        ↓
VersionResolution
        ↓
explicit ContractOps authorization / APPLY / PUBLISH
```

`VersionResolution` is read-only planning output. Resolving a version does not mutate the ODCS contract, write Git state, or publish anything.

## Recommended usage

Choose version authority from the **release topology**, not simply from whether the contract files are stored in Git.

| Repository / release topology | Recommended authority | Version owner |
| --- | --- | --- |
| A contracts repository contains many independently governed contracts | `semapact` | Each contract owns its own ODCS version |
| A contract lives with the data product/code it describes and they are released together | `git` | The product/repository Git release tag owns the version |

### Recommended default: `semapact`

Use SemaPact-managed authority when contracts are centrally governed and their lifecycles are independent, even when all contract files are stored in one Git repository.

```text
contracts/
├── orders.yaml      version: 1.3.0
├── customers.yaml   version: 4.7.3
└── payments.yaml    version: 3.0.0
```

The Git repository is the storage and collaboration boundary; it is **not** the version boundary. Each contract can receive a different semantic-version bump from its own governed changes.

Do not choose Git-managed authority merely because the contracts repository uses Git or CI/CD.

### Recommended co-versioning case: `git`

Use Git-managed authority when one repository represents a releasable data product and contains both the product implementation and its contract.

```text
orders-data-product/
├── src/...
├── pipelines/...
├── contract.yaml
└── deployment/...

Git release: v1.4.0
```

In this topology the product and contract are intentionally co-versioned:

```text
Git tag v1.4.0
    ↓
data product release = 1.4.0
    ↓
contract.version = 1.4.0
```

SemaPact does not calculate a competing contract version. It validates that the Git-selected version satisfies the contract's governance-required minimum bump.

### Decision rule

```text
Does the contract have an independent lifecycle/version from the code or product it describes?

YES
→ use semapact
→ version each contract independently

NO, the contract and data product are deliberately released as one versioned unit
→ use git
→ let the Git/data-product release tag select the contract version
```

If the repository topology is ambiguous, prefer `semapact` until the product and contract have an explicit co-versioning policy. This avoids accidentally coupling otherwise independent contract lifecycles to a repository-wide release number.

## SemaPact-managed versions

This is the default mode for a contract repository that can contain many governed contracts while each contract retains its own independent ODCS lifecycle and version.

```yaml
release:
  versionAuthority: semapact
```

SemaPact selects the smallest valid next release version separately for each contract from that contract's current released ODCS version:

| Governance minimum | Current | Selected |
| --- | --- | --- |
| `none` | `1.2.3` | `1.2.4` |
| `minor` | `1.2.3` | `1.3.0` |
| `major` | `1.2.3` | `2.0.0` |

For example, two contracts in the same repository can evolve independently:

```text
orders     1.2.3 + minor → 1.3.0
customers  4.7.2 + none  → 4.7.3
```

Their versions are not coupled merely because they are stored in the same Git repository.

`none` means governance does not require a minor or major bump. When an already-planned governed revision is explicitly released, the smallest distinct release version is therefore a patch bump.

## Git-managed versions

Git-managed mode is intended for a different repository topology: the data product implementation and its contract live and release together in the same repository. The product/repository Git tag owns the release version, and the contract follows that version.

```yaml
release:
  versionAuthority: git
  tagPattern: "v{version}"
```

For example:

```text
contract + data product repo tag = v1.4.0
        ↓
Git-selected release version = 1.4.0
        ↓
SemaPact validates 1.4.0 against the contract's requiredVersionBump
        ↓
VersionResolution.selectedVersion = 1.4.0
```

SemaPact does not calculate a competing contract version in Git-managed mode. The later APPLY boundary can synchronize the Git-selected value into canonical ODCS `version`.

The release reference is repository/workflow provenance, not a per-contract tag convention. SemaPact therefore does not derive tag names from `contractId`.

A repository can use a literal product-specific prefix when that is its own release convention:

```yaml
release:
  versionAuthority: git
  tagPattern: "orders-data-product/v{version}"
```

The only supported placeholder is:

- `{version}` — required exactly once

All other pattern text is literal. Unknown placeholders fail closed.

## Configuration precedence

`VersionAuthorityService` uses the existing SemaPact configuration hierarchy. Environment variables can explicitly override file configuration:

```text
SEMAPACT_RELEASE_VERSION_AUTHORITY
SEMAPACT_RELEASE_TAG_PATTERN
```

The corresponding YAML keys are:

```text
release.versionAuthority
release.tagPattern
```

A Git authority without `tagPattern`, or a SemaPact authority with a Git-only `tagPattern`, is rejected rather than silently ignored.

## Write boundary

ODCS `version` remains the canonical released contract version, but version resolution itself does not change it. The later explicit ContractOps APPLY boundary owns synchronization of the selected version into the candidate contract. Git tags, SHAs, authority metadata, and deployment provenance remain outside canonical ODCS.
