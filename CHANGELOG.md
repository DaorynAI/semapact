# CHANGELOG

<!-- version list -->

## v0.8.1 (2026-07-01)

### Bug Fixes

- Fix SQL exporter/importer for databricks with consistant location custom property
  ([`96f29d7`](https://github.com/ElliotSun/contract-hub/commit/96f29d74ecb401a72674c184827fce1fb04bf87f))


## v0.8.0 (2026-06-26)

### Bug Fixes

- **merge_engine**: Handle missing nested schema properties and fix customProperties destruction bug
  ([`bd1cb3a`](https://github.com/ElliotSun/contract-hub/commit/bd1cb3a130af5660d062f92e188b84a51141ddf4))

### Features

- **exporter**: Support spark external table via semapact.table.location
  ([`eade008`](https://github.com/ElliotSun/contract-hub/commit/eade0081beb9b7deda80ad8d7b798f7246a0c2ed))


## v0.7.2 (2026-06-11)

### Bug Fixes

- **merge_engine**: Refine relationship merge logic and add missing OVERWRITE_FIELDS
  ([`56f4d1f`](https://github.com/ElliotSun/contract-hub/commit/56f4d1ff65d92b27a4caf698008ba6dea0af7823))


## v0.7.1 (2026-06-06)

### Bug Fixes

- Address various ux and data integrity issues (#5-12)
  ([`73063b1`](https://github.com/ElliotSun/contract-hub/commit/73063b12d74e66b0532dbc3e6b14d416f621fbe5))

- Ensure generated odcs contract complies with v3.1.0 schema (fix invalid binary type and illegal
  chars in stableid)
  ([`0da6265`](https://github.com/ElliotSun/contract-hub/commit/0da6265a18d093ec5cf9053c93da32d1bcc5f5f9))

- Remove redundant delta version from importer customProperties to prevent false positive schema
  drifts
  ([`7f7d58b`](https://github.com/ElliotSun/contract-hub/commit/7f7d58b3806111974e97e9b8c502b56c8d14aee1))

- Resolve raw string credentials and discovery fallback bugs
  ([`4372e3f`](https://github.com/ElliotSun/contract-hub/commit/4372e3f9ddcd8427712b8facdeb2e8007425708c))

- Resolve Windows path parsing, missing OAuth in plan, and logicalTypeOptions schema mapping
  ([`4feaa58`](https://github.com/ElliotSun/contract-hub/commit/4feaa5862e210bea1443eb5cbd199f88bef98f8d))

### Refactoring

- Modularize CLI, implement config layering and plugin registry, fix legacy typing errors
  ([`fe6bd2c`](https://github.com/ElliotSun/contract-hub/commit/fe6bd2cdb39e7842f8a167ec0be14477581c023c))


## v0.7.0 (2026-06-04)

### Bug Fixes

- Map azure.auth_method=cli directly to AzureCliCredential in CLI
  ([`66aaf5b`](https://github.com/ElliotSun/contract-hub/commit/66aaf5b686f064b3641ccb3c404dc72af7d78619))

### Documentation

- Enrich README with Data Engineering and Data Contract SEO keywords
  ([`4819764`](https://github.com/ElliotSun/contract-hub/commit/481976416d47be14a6c6dc2d96bbd6ecb983aae0))

### Features

- Add s3 extra dependencies and bump semapact version to 0.6.0
  ([`d557ced`](https://github.com/ElliotSun/contract-hub/commit/d557ced8704bd1919671fcf197dde9e17ca10cfb))

- Implement StorageAdapterFactory for delta table discovery and add azure auth unit tests
  ([`11a82c5`](https://github.com/ElliotSun/contract-hub/commit/11a82c548bce4c2f3729582d616d3293fb572608))

### Testing

- Add config manager fallback unit tests for Unity Catalog and GitOps workflows
  ([`4d3a556`](https://github.com/ElliotSun/contract-hub/commit/4d3a55661938abcff737b73c19c8a90304d1531b))

- Add config override verification to CLI arguments
  ([`93513b3`](https://github.com/ElliotSun/contract-hub/commit/93513b3206f53353bdb9efc0d84bad8dfbdfee91))


## v0.6.0 (2026-06-02)

### Documentation

- Refactor dependency installation documentation and update CI pipelines to use all-extras for
  development environments
  ([`0665e7d`](https://github.com/ElliotSun/contract-hub/commit/0665e7d86385667132918e9729dddbba4f1cf906))

### Features

- Implement dynamic configuration for Databricks credentials and add AI agent documentation
  ([`1ee4ae4`](https://github.com/ElliotSun/contract-hub/commit/1ee4ae4068aed243c95986951245e347fadd3a70))

- Introduce configuration management system and refine dependency organization with optional feature
  sets
  ([`0960b63`](https://github.com/ElliotSun/contract-hub/commit/0960b63c4d75cf5c3523f79e8665826ebd345633))

- Update contract loader to support apiVersion and v3 prefix, and adjust test error matching and
  configuration mocks
  ([`464e72b`](https://github.com/ElliotSun/contract-hub/commit/464e72b77f6160e5cd1c2ddae59be04c508b81c7))

### Testing

- Add apiVersion to test fixtures and mock ADLS OAuth token resolution in CLI tests
  ([`f46a045`](https://github.com/ElliotSun/contract-hub/commit/f46a045da2af56521f33dc86f5e59ab717540bbe))


## v0.5.0 (2026-05-30)

### Features

- Implement CLI prioritization and intelligent fallback for PR creation
  ([`17595e7`](https://github.com/ElliotSun/contract-hub/commit/17595e7f34969df83b2650c145fe0aa6161f6c77))


## v0.4.0 (2026-05-26)

### Features

- Add dynamic textual tui for semapact commands
  ([`3234dd9`](https://github.com/ElliotSun/contract-hub/commit/3234dd90c6283abd348b3908fdc591e00ae558fa))

### Refactoring

- Remove Streamlit UI components and stabilize pyarrow dependency
  ([`d5a6c4e`](https://github.com/ElliotSun/contract-hub/commit/d5a6c4e15b6badfef01110369e3a041173ed6714))

- Remove Streamlit UI components to keep semapact as a backend-only CLI
  ([`945d45d`](https://github.com/ElliotSun/contract-hub/commit/945d45d2d14173352a1bc08acc54ea26a0edaa2f))


## v0.3.0 (2026-05-21)

### Documentation

- Fix mermaid rendering errors
  ([`fd31730`](https://github.com/ElliotSun/contract-hub/commit/fd3173055622a8f6331ed0f55fc7cff37f015098))

- Optimize mermaid state diagram layout
  ([`0cd80fe`](https://github.com/ElliotSun/contract-hub/commit/0cd80fe19829051681d7f92055d9bcc7a7c56ffb))

- Simplify lifecycle state diagram to reduce clutter
  ([`a63a2af`](https://github.com/ElliotSun/contract-hub/commit/a63a2af52e14f16bac2d403204571d4b337de238))

- Use choice instead of fork in mermaid state diagram
  ([`babfc65`](https://github.com/ElliotSun/contract-hub/commit/babfc65bafe8c19422aaed183fd009fdad54d9b6))

- Use regular text node for choice box in diagram
  ([`51176c5`](https://github.com/ElliotSun/contract-hub/commit/51176c5892a9a6482731f244f96094e19738c3ea))

### Refactoring

- Rename package and installation instructions to `semapact`
  ([`047c0f3`](https://github.com/ElliotSun/contract-hub/commit/047c0f37aba2edcd2fc33428de7b25f245cd2d4b))


## v0.2.0 (2026-05-17)

### Continuous Integration

- Enhance release workflow to support bypass tokens (GitHub App & PAT) for protected branches
  ([`88a11e2`](https://github.com/ElliotSun/contract-hub/commit/88a11e299f481e90f3da319361534e3130cee82a))

### Documentation

- Replace chinese diagram comments and states with english
  ([`aa84bb4`](https://github.com/ElliotSun/contract-hub/commit/aa84bb4ed578e9c6cf20e9a07add07514e237304))

### Features

- Support custom system and user prompt overrides in all enrichment modes
  ([`bb4846a`](https://github.com/ElliotSun/contract-hub/commit/bb4846a62e036ec33295e56afc94f0142ef2fb6a))

### Refactoring

- Add prompt overrides to enricher, fix CLI output handling, and update LLM labeling guidelines
  ([`fcca81a`](https://github.com/ElliotSun/contract-hub/commit/fcca81a2f5b5906af750288dd3c9b7889939fd37))


## v0.1.0 (2026-05-17)

- Initial Release
