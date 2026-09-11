# Governance history persistence

SemaPact persists governance history without moving domain authority into storage.
Canonical artifacts remain owned by their existing domains; history adapters only
store and retrieve those exact immutable models.

The current history boundary is:

```text
GovernanceDecision / ChangeSet
        ↓
GovernanceHistoryRepository
        ↓
GitWorkingTreeHistoryRepository
        ↓
.semapact/history/
```

The Git working-tree adapter writes deterministic JSON files into a SemaPact-owned
path. It does not create Git commits, branches, or pull requests. Normal GitOps
workflows may version those files after SemaPact writes them.

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
