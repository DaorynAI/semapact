# Runtime Product Reconciliation

SemaPact reconciles a governed ODCS data product against an observed runtime product without treating either a single table or Databricks as the core abstraction.

```text
Governed ODCS data product
        ↓
Runtime asset specs
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

## CLI

Databricks is the first runtime provider:

```bash
semapact reconcile \
  --contract ./contracts/sales.yaml \
  --platform databricks \
  --runtime main.sales
```

For the Databricks provider, `--runtime` currently uses `catalog.schema`. Each governed schema is bound to the corresponding physical Unity Catalog asset using its `physicalName` hint when present, otherwise its governed schema name.

`--runtime` is provider-local. Core SemaPact does not define it as a table FQN. A future provider can interpret the same CLI shape differently, for example:

```bash
semapact reconcile --contract sales.yaml --platform snowflake --runtime ANALYTICS.SALES
```

## Authentication

The generic `reconcile` command does not expose Databricks-specific credential flags. The Databricks provider uses the Databricks SDK unified authentication chain. Install provider support with:

```bash
pip install "semapact[databricks]"
```

This keeps the base SemaPact installation and reconciliation core independent from the Databricks SDK.

## Machine-readable output

```bash
semapact reconcile \
  --contract ./contracts/sales.yaml \
  --platform databricks \
  --runtime main.sales \
  --output json
```

JSON output includes the selected provider and runtime target, logical-to-physical bindings, runtime status, deterministic reconciliation differences, stable runtime reason codes, expected/observed values, unverified paths, and the observation fingerprint.

## CI exit codes

Runtime assurance uses additive process outcomes and does not reuse governance blocking semantics:

| Status | Exit code |
| --- | ---: |
| `IN_SYNC` | `0` |
| `DRIFT` | `6` |
| `INDETERMINATE` | `7` |

Existing M0 exit codes remain unchanged: validation `2`, governance blocked `3`, review required `4`, and runtime/infrastructure error `5`.

The reconciliation workflow is read-only. It does not mutate contracts, deploy runtime assets, infer deployment causality, or perform remediation.
