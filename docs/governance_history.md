# Governance history persistence

SemaPact persists governance history without moving domain authority into storage.
Canonical artifacts remain owned by their existing domains; history adapters only
store and retrieve those exact immutable models.

The persistence boundary is capability-oriented:

```text
GovernanceDecision        ChangeSet
        ↓                    ↓
DecisionHistoryRepository  ChangeSetHistoryRepository
          \                  /
           \                /
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
