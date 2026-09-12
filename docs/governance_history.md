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

`ContractRevision` is a revision-domain artifact owned by `semapact/revision/`.
`semapact/history/` only exposes persistence capabilities for it. Persisting a domain
artifact does not transfer semantic ownership to the persistence layer.

The revision package keeps structure, identity rules, and construction separate:

```text
revision/models.py
    ContractRevision / ContractRevisionSource

revision/integrity.py
    fingerprint + UUID formulas + integrity validation

revision/builders.py
    build canonical revision/provenance artifacts
```

SemaPact does not define another contract model. `ContractRevision.contract` uses the
same `OpenDataContractStandard` model used by the ODCS/datacontract-cli stack. The
revision envelope adds only SemaPact-owned identity:

```text
ContractRevision
├── revision_id
├── content_fingerprint
└── contract: OpenDataContractStandard
```

`contract.id`, `contract.version`, schema, quality, servers, and all other ODCS fields
remain authoritative inside the ODCS model. They are not duplicated as revision fields.
Likewise, canonical JSON is not stored as a second logical contract representation; it
is derived transiently when computing or validating revision identity.

Revision identity is computed from the exact ODCS state:

```text
OpenDataContractStandard
      ↓
canonical JSON bytes
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
- reads rehydrate the canonical domain model and invoke domain integrity validation
  before trusting persisted content;
- the embedded artifact ID must match the requested/file identity;
- malformed or semantically inconsistent persisted content fails closed;
- missing IDs produce an explicit history not-found error;
- contract-scoped listings are deterministic.

`ChangeContext` remains part of `ChangeSet` and round-trips with it. History state is
not written into canonical ODCS contracts.

M2 deterministic identities remain authoritative. Persistence does not generate a
replacement identity and does not reinterpret lifecycle, governance, revision,
version, authorization, deployment, or reconciliation semantics.

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
