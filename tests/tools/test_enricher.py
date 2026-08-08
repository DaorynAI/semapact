from unittest.mock import MagicMock
from pathlib import Path
from semapact.tools.enricher import ContractEnricher
from open_data_contract_standard.model import OpenDataContractStandard


def test_contract_enricher(mocker, tmp_path):
    # Mock litellm completion
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[
        0
    ].message.content = '{"potential_joins": [{"source_column": "rcvr_cntry_code", "target_column": "receiver_name", "edge_label": "MOCKED_LABEL", "confidence": 0.8}]}'

    # We patch litellm.completion to mock the completion function
    mock_completion = mocker.patch("litellm.completion", return_value=mock_response)

    # Copy the sample odcs to tmp_path
    sample_path = Path("examples/sample_odcs.yaml")
    test_path = tmp_path / "test_odcs.yaml"
    with open(sample_path, "r") as f:
        test_path.write_text(f.read())

    enricher = ContractEnricher()
    enricher.process(str(test_path), max_workers=2, mode="infer_joins")

    # Validate litellm was called correctly
    assert mock_completion.call_count > 0

    # Read back the enriched YAML
    enriched_odcs = OpenDataContractStandard.from_file(str(test_path))

    # Verify that the semantic edge label was added
    labels_found = 0
    for schema in enriched_odcs.schema_:
        if schema.relationships:
            for rel in schema.relationships:
                if rel.customProperties:
                    for cp in rel.customProperties:
                        if (
                            cp.property == "graph_semantic.edge_label"
                            and cp.value == "MOCKED_LABEL"
                        ):
                            labels_found += 1
        if schema.properties:
            for prop in schema.properties:
                if prop.relationships:
                    for rel in prop.relationships:
                        if rel.customProperties:
                            for cp in rel.customProperties:
                                if (
                                    cp.property == "graph_semantic.edge_label"
                                    and cp.value == "MOCKED_LABEL"
                                ):
                                    labels_found += 1

    assert labels_found > 0


def test_contract_enricher_prompt_overrides(mocker, tmp_path):
    # Mock litellm completion
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"description": "A very custom description of the table."}'

    mock_completion = mocker.patch("litellm.completion", return_value=mock_response)

    sample_path = Path("examples/sample_odcs.yaml")
    test_path = tmp_path / "test_odcs.yaml"
    with open(sample_path, "r") as f:
        test_path.write_text(f.read())

    # Clear description of the tables so they are processed by describe_tables
    odcs_to_clear = OpenDataContractStandard.from_file(str(test_path))
    for schema in odcs_to_clear.schema_:
        schema.description = None
    with open(test_path, "w") as f:
        f.write(odcs_to_clear.to_yaml())

    # We want to overwrite system and user prompt templates
    custom_system_prompt = "Custom system prompt for domain: {domain_context}"
    custom_user_prompt = "Custom user prompt for table {table_name} with columns {columns_info}"

    enricher = ContractEnricher()
    enricher.process(
        str(test_path),
        max_workers=1,
        mode="describe_tables",
        system_prompt=custom_system_prompt,
        user_prompt=custom_user_prompt
    )

    # Verify that litellm was called with the custom formatted prompts
    assert mock_completion.call_count > 0
    called_args, called_kwargs = mock_completion.call_args
    messages = called_kwargs.get("messages", [])

    system_msg = next((m for m in messages if m["role"] == "system"), None)
    user_msg = next((m for m in messages if m["role"] == "user"), None)

    assert system_msg is not None
    assert "Custom system prompt for domain:" in system_msg["content"]
    assert user_msg is not None
    assert "Custom user prompt for table" in user_msg["content"]
