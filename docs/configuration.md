# Configuration

SemaPact loads configuration in this order:

1. explicit CLI override for the current operation;
2. local project config at `.semapact.yaml`;
3. global config at `~/.config/semapact/config.yaml`;
4. feature default.

Operational deployment history is disabled when no backend is configured.

## Databricks connection hints

SemaPact can provide optional Databricks connection hints without replacing the
official SDK unified-authentication chain.

Project configuration:

```yaml
databricks:
  workspace_url: https://adb-<workspace>.<region>.azuredatabricks.net
  profile: DEFAULT
```

A token is also a supported typed field when required:

```yaml
databricks:
  token: <token>
```

Do not commit long-lived credentials to a repository. Prefer a Databricks
profile, workload identity/service-principal authentication, or environment
secrets for CI/CD.

Connection hints resolve in this order:

1. explicit caller/CLI value;
2. `SEMAPACT_DATABRICKS_WORKSPACE_URL`, `SEMAPACT_DATABRICKS_TOKEN`, or `SEMAPACT_DATABRICKS_PROFILE`;
3. local/global SemaPact `databricks` configuration;
4. if still omitted, the Databricks SDK unified-authentication chain, including its standard `DATABRICKS_*` environment variables and profile configuration.

The low-level `create_databricks_workspace_client` factory remains
configuration-neutral. Config resolution happens at SemaPact composition
boundaries before the SDK client is constructed.

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
