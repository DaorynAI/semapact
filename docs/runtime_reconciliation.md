# Runtime Product Reconciliation

SemaPact reconciles a governed ODCS data product against an observed runtime product without treating either a single table or Databricks as the core abstraction.

```text
Governed ODCS data product
        ↓
Runtime location resolution
(contract server first, CLI fallback only when absent)
        ↓
Runtime asset specs from schema.name / physicalName
        ↓
Selected runtime provider
        ↓
Logical ↔ physical bindings
        ↓
ObservedPlatformState
        ↓
ReconciliationResult
        ↓
IN_SYNC / DRIFT / INDETERMINATE
```

## Runtime location precedence

Runtime metadata is resolved deterministically and fail-closed.

1. If the contract defines one `server`, SemaPact uses it automatically.
2. If the contract defines multiple servers, select one with `--server`.
3. If the contract defines no servers, both `--platform` and `--runtime` are required as CLI fallback values.
4. CLI fallback values never override a server already defined by the contract.

The contract remains authoritative for asset identity and physical naming:

```text
schema.name         -> governed logical asset identity
schema.physicalName -> physical runtime asset name
```

CLI fallback supplies only the missing runtime location. It never supplies or rewrites logical-to-physical table mappings.

## CLI

When the contract contains one complete runtime server:

```bash
semapact reconcile --contract ./contracts/sales.yaml
```

When it contains multiple servers:

```bash
semapact reconcile \
  --contract ./contracts/sales.yaml \
  --server production
```

When it contains no server metadata, provide a complete runtime-location fallback:

```bash
semapact reconcile \
  --contract ./contracts/sales.yaml \
  --platform databricks \
  --runtime main.sales
```

For the Databricks provider, the runtime target currently uses `catalog.schema`. Each governed schema is bound to its physical Unity Catalog asset using contract `physicalName` when present, otherwise the governed schema name.

`--runtime` is provider-local. Core SemaPact does not define it as a table FQN; another provider may interpret the target using its own platform-local addressing convention.

## Authentication

The generic `reconcile` command does not expose Databricks-specific credential flags. The selected contract server may provide non-secret connection metadata such as its host. Credentials remain outside the contract and are resolved by the provider authentication mechanism.

The Databricks provider uses the Databricks SDK unified authentication chain. Install provider support with:

```bash
pip install "semapact[databricks]"
```

This keeps the base SemaPact installation and reconciliation core independent from the Databricks SDK.

## Machine-readable output

```bash
semapact reconcile \
  --contract ./contracts/sales.yaml \
  --server production \
  --output json
```

JSON output includes the resolved provider and runtime target, whether runtime metadata came from the contract or CLI fallback, the selected server identifier when applicable, logical-to-physical bindings, runtime status, deterministic reconciliation differences, stable runtime reason codes, expected/observed values, unverified paths, and the observation fingerprint.

## CI exit codes

Runtime assurance uses additive process outcomes and does not reuse governance blocking semantics:

| Status | Exit code |
| --- | ---: |
| `IN_SYNC` | `0` |
| `DRIFT` | `6` |
| `INDETERMINATE` | `7` |

Governance and validation exit codes remain unchanged: validation `2`, governance blocked `3`, review required `4`, and runtime/infrastructure error `5`.

Missing or ambiguous runtime location is a validation failure. Examples include multiple contract servers without `--server`, or a contract with no servers and an incomplete CLI fallback.

The reconciliation workflow is read-only. It does not mutate contracts, deploy runtime assets, infer deployment causality, or perform remediation.
