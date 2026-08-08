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
- **Role:** Converts external data structures (Delta Tables, Spark DDL, Unity Catalog) into Open Data Contract Standard (ODCS) models.
- **Rules:**
  - Must remain strictly stateless and idempotent.
  - **NEVER** place merge, governance, or GitOps logic inside importers.

### B. Core Contract Model
- **Role:** Single canonical representation of the schema and metadata.
- **Rules:**
  - The ODCS YAML/Pydantic model is the single source of truth across the architecture. No alternative models are allowed.

### C. Lifecycle Governance Layer
- **Role:** Handles breaking change checks, deprecation rules, merge policies, and version bump calculations.
- **Rules:**
  - This is the **ONLY** place where contract lifecycle logic is allowed.
  - It must remain fully decoupled from the UI and ingestion layers.

### D. Export Layer
- **Role:** Converts contracts to downstream assets (Great Expectations suites, Spark DDL, Graph cypher).
- **Rules:**
  - Exporters must be read-only and **NEVER** modify the original contracts.

### E. Orchestration Layer
- **Role:** Coordinates multi-step workflows (e.g. import → merge → export → PR).
- **Rules:**
  - Coordinates execution paths but must NOT contain custom business logic.

### F. DevOps Layer
- **Role:** Automates PR creation, version bumps, release manifest building, and metadata auditing.
