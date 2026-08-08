---
name: llm-enricher
description: Core behavior, prompt patterns, and metadata specification for the LLM-powered ContractEnricher. Apply this skill whenever modifying the LLM client, prompts, enricher module, or metadata tags.
---

# LLM Enricher & Metadata Specification

This skill details the functionality, prompts, and metadata schemas of the `ContractEnricher` tool used in SemaPact.

## 1. Core Architecture & Files
- `semapact/tools/enricher.py`: The `ContractEnricher` class iterates over the contract, parses definitions, and executes parallel LLM tasks. Output must be written directly back to the YAML contract.
- `semapact/tools/llm_client.py`: LLM abstraction (`BaseLLMProvider`, `OpenAILLMProvider`) powered by `litellm`. Compatible with standard OpenAI, Azure AI Foundry, Databricks, vLLM, Ollama, etc.
- `semapact/constants.py`: Stores all LLM prompt templates (system and user prompts). Prompt templates must NEVER be hardcoded inside logic modules.

## 2. LLM Provider Configuration
Standard routing expects these environment variables:
- **OpenAI**: `LLM_MODEL_NAME`, `LLM_API_KEY`
- **Azure**: `LLM_MODEL_NAME` (e.g. `azure/...`), `LLM_API_KEY`, `LLM_BASE_URL`
- **Self-Hosted (vLLM/Ollama)**: `LLM_MODEL_NAME` (with `openai/` prefix for vLLM), `LLM_API_KEY` ("dummy"), `LLM_BASE_URL`

## 3. Enrichment Modes & Provenance Specifications

### A. Missing Descriptions (`describe_tables` & `describe_columns`)
- Iterate to find entities lacking a `description`.
- Pass context (entity name, types, sibling columns) to LLM.
- **Rule:** The returned description MUST be prefixed with `[LLM_INFERRED] ` directly in the text.
- **Rule:** The tag `LLM_INFERRED` MUST be appended to the entity's `tags` array.

### B. Quality Rules Suggestion (`suggest_quality`)
- Prompt the LLM to suggest Great Expectations (GE) rules based on column type, description, and primary/required constraints.
- **Rule:** Do NOT generate redundant rules (e.g., no `nullValues mustBe 0` if `required: true` is set).
- **Rule:** Inferred rules must contain the tag `LLM_INFERRED` and the custom property: `graph_semantic.provenance: LLM_INFERRED`.

### C. Potential Join Inference (`infer_joins`)
- Evaluates tables in pairs to infer potential foreign-key joins.
- Create a `Relationship` object in the source column's `relationships` array.
- **Rule:** The relationship MUST contain these exact `customProperties`:
  - `graph_semantic.edge_label`: inferred label
  - `graph_semantic.provenance`: `LLM_INFERRED`
  - `graph_semantic.confidence`: numeric value (e.g., 0.8)

## 4. Testing & LLM Mocking Policy
- **Rule:** Under no circumstances should test suites execute actual LLM requests.
- **Rule:** Always use `pytest-mock` or `unittest.mock.patch` to mock `litellm.completion` and return predefined JSON shapes.
