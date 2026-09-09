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
