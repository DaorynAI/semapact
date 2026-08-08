---
name: odcs-skills
description: Implement and review Open Data Contract Standard (ODCS) extensions and integrations in SemaPact. Use when importing schema metadata, applying deterministic field ordering, or customizing upstream validator behavior.
---

# ODCS Skills & Upstream Compatibility

This skill outlines how SemaPact interfaces with the upstream Open Data Contract Standard (ODCS) models and `datacontract-cli` dependencies.

## 1. Upstream Dependency Directives (CRITICAL)
- **Do NOT reinvent `datacontract-cli` internals.** SemaPact is an extension layer above `datacontract-cli`.
- **Core Validation:** Always use upstream validators (`datacontract-cli` pydantic/schema logic) for core ODCS schema validation (structure, data types, standard quality rules formatting). 
- **Custom Validation:** Custom validators implemented inside SemaPact must ONLY target SemaPact-specific metadata rules, business constraints, or semantic relationship policies.
- **Importers/Exporters:** Custom importers (e.g. Unity, DDL, SQL folder) must inherit from or conform strictly to upstream importer protocols, and register via the standard factory.

## 2. Deterministic Serialization & GitOps Ordering
To prevent erratic Git diffs and support seamless GitOps branch comparisons, all generated ODCS YAML files must apply strict lexicographical sorting:
- Sort `schema` (tables) by `name`.
- Sort `properties` (columns) by `name`.
- Sort `quality` rules by the target entity/column `name`.
- Sort `customProperties` by property key name.

## 3. Extension & Custom Metadata Mapping
SemaPact extends the core ODCS with custom properties located strictly in the `customProperties` section:
- Use `graph_semantic.edge_label` for relationship mapping.
- Use `graph_semantic.provenance` to track metadata origin (e.g. `DDL`, `LLM_INFERRED`).
- Use `graph_export.is_junction_edge` for collapsing join relationships.

## 4. Policy Delegation
- All rules regarding **breaking changes**, **auto-deprecation**, and **lifecycle states** are governed exclusively by the [lifecycle-policy](../lifecycle-policy/SKILL.md) skill. Do NOT redefine or duplicate these rules here.
