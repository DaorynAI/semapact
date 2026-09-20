# Configuration

SemaPact loads configuration in this order:

1. explicit CLI override for the current operation;
2. local project config at `.semapact.yaml`;
3. global config at `~/.config/semapact/config.yaml`;
4. feature default.

Operational deployment history is disabled when no backend is configured.

## Operational history

SQLite:

```yaml
history:
  operational:
    backend: sqlite
    path: .semapact/operational.db
```

Delta:

```yaml
history:
  operational:
    backend: delta
    table_uri: s3://governance/semapact/operational-history
```

The configuration is validated fail closed. Supported backends require exactly their backend-specific fields:

- `sqlite`: `backend` + `path`;
- `delta`: `backend` + `table_uri`.

Unknown backends, missing required fields, and extra fields under `history.operational` are rejected.

The canonical schema is defined by `SemaPactConfigSchema` and published for editor/tooling use at:

```text
schemas/semapact-config.schema.json
```

## CLI override

`--operational-history` is a per-invocation override, not the normal configuration path.

For example:

```bash
semapact deployment deploy \
  --bundle ./artifacts/orders.bundle.json \
  --operational-history sqlite:///./tmp/one-run.db
```

If the flag is omitted, SemaPact resolves `history.operational` from project/global config. If neither exists, operational history persistence remains disabled.

Operational telemetry is separate from the Git governance ledger. Formal release/approval facts may be stored in Git, while high-frequency deployment events are written only to an explicitly configured SQLite or Delta backend.
