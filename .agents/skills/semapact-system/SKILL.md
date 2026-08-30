---
name: semapact-system
description: Defines the core operating model, layered architecture boundaries, and change-driven workflow of SemaPact. Apply this skill when refactoring components, implementing new modules, or deciding boundary placement.
---

# SemaPact System Model & Architecture Rules

SemaPact is an enterprise data contract control plane and governance platform. It follows a strict layered architecture and a change-driven operating model.

## 1. Core Workflow Principles
- **Change-Driven System:** All UI edits must happen via drafts.
  - Save = save draft copy.
  - Publish/Promote = run governance checks and promote draft.
- **Immutability of Main:** Main production contracts are immutable from direct UI edits. They are only updated via governed merge operations.
- **Immutability of Identity:** The contract `id` is immutable once created.
- **Release Gating:** Contract `version` is release-managed and only changes through an explicit release/promotion path.

## 2. Layered Architecture Boundaries (CRITICAL)

### A. Ingestion / Import Layer
- **Role:** Converts external data structures (Delta Tables, Spark DDL, Unity Catalog) into Open Data Contract Standard (ODCS) models when a contract import is explicitly requested.
- **Rules:**
  - Must remain strictly stateless and idempotent.
  - **NEVER** place merge, governance, or GitOps logic inside importers.
  - Contract import is distinct from runtime observation; observing a platform must not implicitly create or mutate an ODCS contract.

### B. Governed Contract Model
- **Role:** Single canonical representation of governed desired contract state.
- **Rules:**
  - The ODCS YAML/Pydantic model is the single source of truth for governed contract state.
  - Runtime platform metadata must not become governed truth merely because it was observed.

### C. Runtime Observation Model
- **Role:** Represents point-in-time external runtime state for assurance and reconciliation workflows.
- **Rules:**
  - `ObservedContractState` is a read-side model, not an alternative canonical contract format.
  - Runtime identity is platform-local and must remain distinct from ODCS contract identity.
  - Observation must not invoke lifecycle merge, governance evaluation, release mutation, or platform writeback.
  - Converting observed state into an ODCS contract is an explicit import workflow, never an implicit observation side effect.

### D. Lifecycle Governance Layer
- **Role:** Handles breaking change checks, deprecation rules, merge policies, and version bump calculations.
- **Rules:**
  - This is the **ONLY** place where contract lifecycle logic is allowed.
  - It must remain fully decoupled from the UI, ingestion, and runtime observation layers.

### E. Export Layer
- **Role:** Converts contracts to downstream assets (Great Expectations suites, Spark DDL, Graph cypher).
- **Rules:**
  - Exporters must be read-only and **NEVER** modify the original contracts.

### F. Orchestration Layer
- **Role:** Coordinates multi-step workflows (e.g. import → merge → export → PR).
- **Rules:**
  - Coordinates execution paths but must NOT contain custom business logic.

### G. DevOps Layer
- **Role:** Automates PR creation, version bumps, release manifest building, and metadata auditing.
