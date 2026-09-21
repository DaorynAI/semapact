# Live Databricks smoke

The live Databricks smoke is an opt-in production-integration check for the canonical SemaPact Data Engineer workflow.

It is intentionally separate from normal PR CI.

## What it proves

The smoke runs against a real Databricks workspace and exercises:

```text
candidate desired state
→ CREATE in UAT
→ fresh IN_SYNC

candidate schema evolution
→ ADD nullable column in UAT
→ fresh IN_SYNC

formal release
→ ContractRelease

ContractRelease
→ CREATE in PROD
→ fresh IN_SYNC
→ Unity Catalog release provenance tags

same ContractRelease again
→ NO_OP
→ fresh IN_SYNC
→ provenance projection remains idempotent
```

Candidate deployment must not create formal release provenance tags.

## Safety boundary

The smoke only creates generated tables whose names begin with:

```text
semapact_smoke_
```

Both configured schemas must also begin with:

```text
semapact_smoke_
```

The schemas must already exist. The smoke never creates or deletes catalogs or schemas.

Each run uses a unique table name derived from the GitHub Actions run ID. Cleanup deletes only those exact generated tables.

The test also requires the explicit confirmation value:

```text
SEMAPACT_LIVE_DATABRICKS_CONFIRM=I_UNDERSTAND_THIS_CREATES_TABLES
```

## GitHub Actions

Run:

```text
Live Databricks Smoke
```

through `workflow_dispatch`.

The workflow uses the protected GitHub Environment:

```text
databricks-smoke
```

Configure the environment with Databricks unified-auth credentials. Supported standard environment secrets include:

```text
DATABRICKS_HOST

# PAT option
DATABRICKS_TOKEN

# OAuth service-principal option
DATABRICKS_CLIENT_ID
DATABRICKS_CLIENT_SECRET
```

Do not configure both authentication approaches unless the Databricks SDK configuration intentionally requires it.

Workflow inputs provide:

```text
catalog
uat_schema
prod_schema
warehouse_id
```

Recommended dedicated schemas:

```text
semapact_smoke_uat
semapact_smoke_prod
```

## Required Databricks capability

The smoke identity must be able to:

* use the configured catalog and smoke schemas;
* observe table metadata;
* create managed Delta tables in the smoke schemas;
* add a nullable column;
* query the catalog information schema for table tags;
* apply/remove SemaPact-owned table tags;
* delete only the generated smoke tables during cleanup;
* execute the required SQL through the configured warehouse.

The more general least-privilege production identity design remains tracked separately in the private roadmap.

## Local execution

The test is skipped unless explicitly enabled.

Example environment:

```text
SEMAPACT_RUN_LIVE_DATABRICKS=1
SEMAPACT_LIVE_DATABRICKS_CONFIRM=I_UNDERSTAND_THIS_CREATES_TABLES
SEMAPACT_LIVE_DATABRICKS_CATALOG=<catalog>
SEMAPACT_LIVE_DATABRICKS_UAT_SCHEMA=semapact_smoke_uat
SEMAPACT_LIVE_DATABRICKS_PROD_SCHEMA=semapact_smoke_prod
SEMAPACT_LIVE_DATABRICKS_WAREHOUSE_ID=<warehouse-id>
SEMAPACT_LIVE_RUN_ID=local_001
```

Then run:

```bash
pytest tests/live/test_databricks_release_deployment_smoke.py -m live_databricks -vv
```

Databricks authentication is resolved by the official SDK through its normal unified-auth configuration.

## Non-goals

This smoke does not test:

* destructive schema evolution;
* rename/type/nullability migration;
* customer production tables;
* performance or load;
* continuous monitoring;
* infrastructure provisioning.
