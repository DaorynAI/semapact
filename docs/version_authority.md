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

Git-managed mode makes an external release reference authoritative for the actual version:

```yaml
release:
  versionAuthority: git
  tagPattern: "v{version}"
```

or a contract-scoped tag:

```yaml
release:
  versionAuthority: git
  tagPattern: "{contractId}/v{version}"
```

The caller supplies the exact release reference, for example `v1.4.0` or `orders-product/v2.0.0`. SemaPact extracts that version and validates it against `ReleasePlan.requiredVersionBump`; it never substitutes a different version in Git-managed mode.

Supported tag-pattern placeholders are exactly:

- `{version}` — required exactly once
- `{contractId}` — optional, at most once

All other pattern text is matched literally. Unknown placeholders fail closed.

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
