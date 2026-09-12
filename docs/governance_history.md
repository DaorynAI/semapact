# Governance history persistence

SemaPact persists governance history without moving domain authority into storage.
Canonical artifacts remain owned by their existing domains; history adapters only
store and retrieve those exact immutable models.

The persistence boundary is capability-oriented:

```text
GovernanceDecision   ChangeSet   ContractRevision   RevisionSource
        ↓                ↓               ↓                ↓
DecisionHistory      ChangeSetHistory    RevisionHistory   RevisionSourceHistory
Repository           Repository          Repository        Repository
          \              |                  |              /
           \             |                  |             /
             GitWorkingTreeHistoryRepository
                           ↓
                 .semapact/history/
```

Callers depend only on the narrow typed repository capability they need. A physical
backend may implement several repository protocols through one shared storage kernel.
This avoids a single growing history interface while still allowing Git, SQLite, and
Delta implementations to share backend-specific mechanics.

The Git working-tree adapter writes deterministic JSON files into a SemaPact-owned
path. It does not create Git commits, branches, or pull requests. Normal GitOps
workflows may version those files after SemaPact writes them.

No application service is introduced merely to proxy repository methods. A history
query/application service belongs above these ports only when a use case actually
coordinates multiple artifact types, for example evolution-chain reconstruction or a
cross-artifact timeline.

## Contract revision identity

`ContractRevision` identifies exact canonical ODCS content. It is deliberately
separate from semantic version and source-control provenance.

```text
exact ODCS contract
      ↓
canonical JSON
      ↓
SHA-256 content fingerprint
      ↓
UUIDv5 revision ID
```

The canonical JSON representation uses ODCS alias names, excludes absent (`None`)
fields, preserves list order, and sorts object keys through SemaPact's canonical JSON
serializer. The fixed ContractRevision UUID namespace is part of the identity protocol;
changing it is an identity-schema migration.

A Git SHA, branch, tag, registry URI, or other external source reference does not
participate in revision identity. Source provenance is represented as a separate
immutable `ContractRevisionSource` link:

```text
ContractRevision
   ├── source A
   ├── source B
   └── source C
```

Therefore the same canonical contract content has the same revision ID wherever it is
observed, while all known source references can still be retained independently.

## Persistence semantics

For supported artifacts:

- writing identical content under the same artifact ID is idempotent;
- writing different content under an existing artifact ID fails closed;
- reads rehydrate and validate the canonical domain model;
- the embedded artifact ID must match the requested/file identity;
- malformed or invalid persisted content fails closed;
- missing IDs produce an explicit history not-found error;
- contract-scoped listings are deterministic.

`ChangeContext` remains part of `ChangeSet` and round-trips with it. History state is
not written into canonical ODCS contracts.

M2 deterministic identities remain authoritative. Persistence does not generate a
replacement identity and does not reinterpret lifecycle, governance, version,
authorization, deployment, or reconciliation semantics.

## Backend extension rule

Logical ports remain typed by domain artifact. Physical representation belongs to the
backend adapter:

```text
Git      → canonical JSON files
SQLite   → relational rows/schema
Delta    → append-oriented Delta rows/schema
```

Backend-specific row/file models must not replace or leak into the canonical domain
artifacts. Future artifact types add their own narrow persistence capability rather
than expanding one universal repository interface.
