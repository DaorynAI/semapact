# Runtime Reconciliation

SemaPact can compare one governed ODCS contract with one observed Databricks Unity Catalog table through the M1 read-side reconciliation flow.

Install Databricks support when it is not already present:

```bash
pip install "semapact[databricks]"
```

## CLI

```bash
semapact reconcile \
  --contract ./contracts/orders.yaml \
  --source main.sales.orders
```

The command uses the Databricks SDK unified authentication chain by default. Optional hints can be supplied with `--workspace-url`, `--token`, or `--profile`.

For deterministic machine-readable output:

```bash
semapact reconcile \
  --contract ./contracts/orders.yaml \
  --source main.sales.orders \
  --output json
```

The command is read-only. It does not modify the governed contract or Unity Catalog.

## Status and CI exit codes

| M1 status | Exit code | Meaning |
| --- | ---: | --- |
| `IN_SYNC` | `0` | All supported governed comparisons were verified and no difference was found. |
| `DRIFT` | `6` | At least one supported runtime difference was proven. |
| `INDETERMINATE` | `7` | No proven difference exists, but at least one governed comparison could not be verified from available runtime evidence. |

Existing validation, governance, and runtime-error exit codes remain unchanged.

A CI step can therefore use the command directly:

```bash
semapact reconcile \
  --contract ./contracts/orders.yaml \
  --source main.sales.orders \
  --profile ci \
  --output json > reconciliation.json
```

A non-zero exit distinguishes proven drift (`6`), incomplete runtime evidence (`7`), and normal SemaPact validation/governance/runtime failures without reinterpreting the JSON payload.
