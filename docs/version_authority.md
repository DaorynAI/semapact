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

This is the default mode:

```yaml
release:
  versionAuthority: semapact
```

SemaPact selects the smallest valid next release version from the current released ODCS version:

| Governance minimum | Current | Selected |
| --- | --- | --- |
| `none` | `1.2.3` | `1.2.4` |
| `minor` | `1.2.3` | `1.3.0` |
| `major` | `1.2.3` | `2.0.0` |

`none` means governance does not require a minor or major bump. When an already-planned governed revision is explicitly released, the smallest distinct release version is therefore a patch bump.

## Git-managed versions

Git-managed mode delegates version selection to the repository or data-product release process. This is a natural fit when the data product implementation and its contract are released from the same repository.

```yaml
release:
  versionAuthority: git
  tagPattern: "v{version}"
```

For example, a repository release/tag `v1.4.0` selects release version `1.4.0`. SemaPact does not calculate a competing contract version. It validates the Git-selected version against this contract's `ReleasePlan.requiredVersionBump` and later APPLY can synchronize the selected value into canonical ODCS `version`.

The release reference is repository/workflow provenance, not a per-contract tag convention. SemaPact therefore does not derive tag names from `contractId` or prescribe how a repository separates multiple products.

A repository can still use a literal product-specific prefix when that is its release convention:

```yaml
release:
  versionAuthority: git
  tagPattern: "orders-data-product/v{version}"
```

The only supported placeholder is:

- `{version}` — required exactly once

All other pattern text is literal. Unknown placeholders fail closed.

If one repository releases multiple contracts/data products under one repository version, the same Git release version can be validated independently against each contract's governance minimum. The resulting `VersionResolution` remains per-contract because governance and release authorization remain contract-scoped, even though Git selected the shared release version.

If a monorepo independently releases different products, the repository workflow is responsible for supplying the correct release reference/configuration for the product being released. SemaPact does not invent per-contract Git tags.

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
