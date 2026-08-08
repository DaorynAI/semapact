# SemaPact Enricher Specification

This document details the functionality, prompts, and behaviors of the `ContractEnricher` tool used in SemaPact.

The main purpose of the `ContractEnricher` is to leverage a Large Language Model (LLM) to infer semantic relationships between database tables, descriptions for tables and columns, and basic Data Quality rules.

## Architecture

The Enricher module is comprised of several key components that work together to apply LLM inferences to ODCS models:

- `semapact/tools/enricher.py`: Contains the `ContractEnricher` class, which is responsible for iterating through the ODCS contract (tables and columns), parsing schema definitions, and preparing parallel tasks for LLM inferences. It writes the generated outputs directly back to the contract file.
- `semapact/tools/llm_client.py`: Provides the abstraction layers (`BaseLLMProvider`, `OpenAILLMProvider`) used by the enricher to communicate with Large Language Models. It is powered by `litellm` under the hood, enabling seamless compatibility with OpenAI, Azure AI Foundry, Databricks, vLLM, Ollama, and over 100 other LLM providers.
- `semapact/constants.py`: Stores the system and user prompt templates used by the enricher. Moving these templates into a central constants file prevents the enricher logic from being cluttered by hard-coded prompts and promotes reusability.

## LLM Provider Configuration
The `OpenAILLMProvider` is highly configurable via environment variables, leveraging `litellm`'s native routing.

```bash
# For standard OpenAI
export LLM_MODEL_NAME="gpt-4-turbo"
export LLM_API_KEY="sk-..."

# For Azure AI Foundry
export LLM_MODEL_NAME="azure/gpt-4o"
export LLM_API_KEY="azure-api-key"
export LLM_BASE_URL="https://your-endpoint.openai.azure.com/"

# For Self-Hosted vLLM or Ollama
export LLM_MODEL_NAME="openai/mistral" # Use openai/ prefix for vLLM
export LLM_API_KEY="dummy"
export LLM_BASE_URL="http://localhost:8000/v1"
```

## How to Invoke the Enricher using the SDK

You can initialize and run the `ContractEnricher` programmatically using the Python SDK.

### Code Example

```python
from semapact.tools.enricher import ContractEnricher
from semapact.tools.llm_client import OpenAILLMProvider

provider = OpenAILLMProvider()
enricher = ContractEnricher(llm_provider=provider)

# Run the enricher in 'infer_joins' mode
enricher.process(contract_path="path/to/datacontract.yaml", max_workers=2, mode="infer_joins")

# Available Modes:
# - 'label': infers semantic edge labels for existing relationships
# - 'infer_joins': predicts new potential relationships based on descriptions
# - 'describe_tables': generates missing descriptions for tables
# - 'describe_columns': generates missing descriptions for columns
# - 'suggest_quality': generates base GE quality rules for columns based on descriptions
```

## Workflows

### Missing Descriptions (Tables and Columns)
When running `describe_tables` or `describe_columns`, the enricher iterates through the contract to find entities that lack a `description`. It passes the context (e.g. table name, column types, other existing columns) to the LLM.
- The returned description is prefixed with `[LLM_INFERRED] ` directly in the text to explicitly indicate its provenance.
- The tag `LLM_INFERRED` is also added to the entity's `tags` array.

### Quality Rules Suggestion
When running `suggest_quality`, the enricher iterates through the properties of the contract and asks the LLM to suggest Great Expectations (GE) rules based on the column's type, description, and primary/required constraints.
- The prompt explicitly instructs the LLM not to generate redundant rules (e.g. `nullValues: mustBe 0` on a column that already has `required: true`).
- Inferred rules are written to the `quality` array of the property.
- To distinguish them from human-authored rules, inferred rules contain the tag `LLM_INFERRED` and a custom property: `graph_semantic.provenance: LLM_INFERRED`.

### Potential Join Inference
To accurately and efficiently infer potential joins between tables that lack explicitly defined foreign keys, the `ContractEnricher` evaluates tables in pairs.
- It locates the `source_column` in the Source Table.
- It creates a new `Relationship` object in that column's `relationships` array.
- Appends `customProperties` for `graph_semantic.edge_label`, `graph_semantic.provenance: LLM_INFERRED`, and `graph_semantic.confidence`.

This perfectly aligns with downstream artifact generation (such as Cypher and JSON Graph Exports) which look for these exact fields.
