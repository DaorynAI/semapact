import pytest
from pathlib import Path
import json

from semapact.exporters.graph_exporter import GraphExporter
from datacontract.data_contract import DataContract


@pytest.fixture
def sample_graph_yaml() -> Path:
    fixture_path = Path("tests/fixtures/contracts/odcs/graph_sample.yaml")
    return fixture_path


def test_graph_exporter_nodes(sample_graph_yaml):
    nodes, edges = GraphExporter.from_yaml(sample_graph_yaml, export_args={"format": "raw"})

    # 10 tables + 21 columns = 31 nodes
    assert len(nodes) == 31

    users_table_node = next(n for n in nodes if n.name == "users" and n.type == "Table")
    assert users_table_node.properties.get("businessName") == "Users Table"
    assert (
        users_table_node.properties.get("dataGranularityDescription")
        == "One row per user"
    )

    users_email_node = next(
        n for n in nodes if n.name == "users.email" and n.type == "Column"
    )
    assert users_email_node.properties.get("businessName") == "User Email Address"

    # Assert quality matches the serialized ODCS library type expectation
    quality_prop = users_email_node.properties.get("quality")
    assert isinstance(quality_prop, list)
    assert len(quality_prop) == 1
    assert quality_prop[0]["id"] == "email_valid_format"
    assert quality_prop[0]["metric"] == "invalidValues"
    assert quality_prop[0]["arguments"]["pattern"] == "^.+@.+$"
    assert quality_prop[0]["mustBe"] == 0

    created_at_node = next(
        n
        for n in nodes
        if n.name == "loyalty_members.created_at" and n.type == "Column"
    )
    assert created_at_node.properties.get("format") == "yyyy-MM-ddTHH:mm:ssZ"
    examples_prop = created_at_node.properties.get("examples")
    assert isinstance(examples_prop, list)
    assert "2024-03-10T14:22:35Z" in examples_prop
    assert len(examples_prop) == 2

    node_names = {n.name for n in nodes}
    assert "users" in node_names
    assert "orders" in node_names
    assert "loyalty_members" in node_names
    assert "user_products_junction" in node_names
    assert "users.id" in node_names
    assert "users.email" in node_names


def test_graph_exporter_edges(sample_graph_yaml):
    nodes, edges = GraphExporter.from_yaml(sample_graph_yaml, export_args={"format": "raw"})

    # 9 table semantic edges + 21 HAS_COLUMN edges = 30 edges
    assert len(edges) == 30

    import json

    # Check explicit label (Table to Table)
    edge1 = next(e for e in edges if e.label == "PLACED_BY")
    assert edge1.source == "orders"
    assert edge1.target == "users"
    assert edge1.is_junction_edge is False
    assert json.loads(edge1.properties.get("source_columns")) == ["customer_id"]
    assert json.loads(edge1.properties.get("target_columns")) == ["id"]
    assert edge1.properties.get("provenance") == "DDL"

    # Check junction edge marking
    edge2 = next(e for e in edges if e.target == "loyalty_members")
    assert edge2.source == "orders"
    assert edge2.label == "LOYALTY_MEMBERS"  # fallback
    assert edge2.is_junction_edge is True
    assert edge2.properties.get("name") == "orders"
    assert edge2.properties.get("businessName") == "Orders Table"
    assert json.loads(edge2.properties.get("source_columns")) == ["customer_id"]
    assert json.loads(edge2.properties.get("target_columns")) == ["customer_id"]
    assert edge2.properties.get("provenance") == "DDL"

    # Check another fallback
    edge3 = next(e for e in edges if e.label == "PRODUCTS" and e.source == "orders")
    assert edge3.source == "orders"
    assert edge3.target == "products"
    assert edge3.is_junction_edge is False

    # Check schema level composite keys array stripping
    edge_complex = next(e for e in edges if e.label == "COMPLEX_JUNCTION")
    assert json.loads(edge_complex.properties.get("source_columns")) == [
        "order_id",
        "product_id",
    ]
    assert json.loads(edge_complex.properties.get("target_columns")) == [
        "order_id",
        "product_id",
    ]

    # Check schema level self reference with arrays
    edge4 = next(
        e for e in edges if e.source == "employees" and e.target == "employees"
    )
    assert edge4.source == "employees"
    assert edge4.label == "EMPLOYEES"
    assert json.loads(edge4.properties.get("source_columns")) == ["manager_id"]
    assert json.loads(edge4.properties.get("target_columns")) == ["id"]

    # Check provenance
    edge_purchased = next(e for e in edges if e.label == "PURCHASED")
    assert edge_purchased.properties.get("provenance") == "LLM_INFERRED"
    assert edge_purchased.properties.get("confidence") == 0.85

    # Check HAS_COLUMN edges exist
    has_col_edges = [e for e in edges if e.label == "HAS_COLUMN"]
    assert len(has_col_edges) == 21
    user_id_col = next(
        e for e in has_col_edges if e.source == "users" and e.target == "users.id"
    )
    assert user_id_col is not None


def test_graph_exporter_cypher_from_yaml(sample_graph_yaml):
    contract = DataContract(data_contract_file=str(sample_graph_yaml))
    exporter = GraphExporter(export_format="graph")

    # Force the sdk to parse the contract (mimics CLI initialization)
    if contract.get_data_contract() is None:
        contract.get_data_contract()  # Initialize cache

    contract_model = getattr(
        contract,
        "contract",
        getattr(contract, "_data_contract", contract.get_data_contract()),
    )
    if contract_model is None:
        from semapact.utils.schema_utils import contract_to_model

        contract_model = contract_to_model(sample_graph_yaml)

    result = exporter.export(
        data_contract=contract_model, export_args={"format": "cypher"}
    )

    assert "CREATE" in result
    assert "MERGE" not in result

    # Simple check on one of the relationships and nodes to ensure proper format was achieved
    assert "[:PLACED_BY" in result
    assert "[:HAS_COLUMN" in result
    # Check that self referencing mapping behaves properly within output sequence
    assert "[:EMPLOYEES" in result


def test_graph_exporter_json_from_yaml(sample_graph_yaml):
    contract = DataContract(data_contract_file=str(sample_graph_yaml))
    exporter = GraphExporter(export_format="graph")

    # Force the sdk to parse the contract (mimics CLI initialization)
    if contract.get_data_contract() is None:
        contract.get_data_contract()  # Initialize cache

    contract_model = getattr(
        contract,
        "contract",
        getattr(contract, "_data_contract", contract.get_data_contract()),
    )
    if contract_model is None:
        from semapact.utils.schema_utils import contract_to_model

        contract_model = contract_to_model(sample_graph_yaml)

    result_str = exporter.export(
        data_contract=contract_model, export_args={"format": "json"}
    )
    result = json.loads(result_str)

    assert "nodes" in result
    assert "edges" in result

    assert len(result["nodes"]) == 31
    assert len(result["edges"]) == 30

    # Assert zero indexing applies correctly
    ids = [n["id"] for n in result["nodes"]]
    assert min(ids) == 0
    assert max(ids) == 30

    # Assert mapping relationships
    placed_by_edge = next(e for e in result["edges"] if e["type"] == "PLACED_BY")
    assert placed_by_edge["source"] is not None
    assert placed_by_edge["target"] is not None
