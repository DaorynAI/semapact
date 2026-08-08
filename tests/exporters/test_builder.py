import pytest
from pathlib import Path
from semapact.exporters.builder import InMemoryGraphBuilder
from open_data_contract_standard.model import OpenDataContractStandard


@pytest.fixture
def sample_graph_yaml_path() -> Path:
    return Path("tests/fixtures/contracts/odcs/graph_sample.yaml")


def test_in_memory_graph_builder(sample_graph_yaml_path):
    import networkx as nx
    from semapact.utils.schema_utils import contract_to_model

    contract: OpenDataContractStandard = contract_to_model(sample_graph_yaml_path)

    # Store original state for validation
    original_schema_len = len(contract.schema_ or [])

    builder = InMemoryGraphBuilder(contract)
    graph = builder.build()

    # Verify graph type
    assert isinstance(graph, nx.MultiDiGraph)

    # Verify nodes
    nodes = list(graph.nodes)
    assert len(nodes) == 8
    assert "users" in nodes
    assert "loyalty_members" in nodes
    assert "products" in nodes
    assert "orders" in nodes
    assert "order_items" in nodes
    assert "product_inventory" in nodes
    assert "employees" in nodes
    assert "reversed_order_edge" in nodes
    assert "user_products_junction" not in nodes
    assert "complex_junction" not in nodes

    # Verify regular edges
    # orders -> users (PLACED_BY)
    edge_data_users = graph.get_edge_data("orders", "users")
    assert edge_data_users is not None
    assert edge_data_users[0]["label"] == "PLACED_BY"
    assert edge_data_users[0]["is_junction_edge"] is False

    # orders -> products (PRODUCTS fallback)
    edge_data_prods = graph.get_edge_data("orders", "products")
    assert edge_data_prods is not None
    assert edge_data_prods[0]["label"] == "PRODUCTS"
    assert edge_data_prods[0]["is_junction_edge"] is False

    # products -> reversed_order_edge (HAS_ORDER, because of is_source=true)
    edge_data_prods_rev = graph.get_edge_data("products", "reversed_order_edge")
    assert edge_data_prods_rev is not None
    assert edge_data_prods_rev[0]["label"] == "HAS_ORDER"
    assert edge_data_prods_rev[0]["is_junction_edge"] is False

    # Verify junction edge
    # users -> products (PURCHASED)
    edge_data_junc = graph.get_edge_data("users", "products")
    assert edge_data_junc is not None
    assert edge_data_junc[0]["label"] == "PURCHASED"
    assert edge_data_junc[0]["is_junction_edge"] is True
    assert edge_data_junc[0]["active"] == "boolean"
    assert edge_data_junc[0]["score"] == "float"

    # Verify composite key junction edge
    edge_data_comp = graph.get_edge_data("order_items", "product_inventory")
    assert edge_data_comp is not None
    assert edge_data_comp[0]["label"] == "COMPLEX_JUNCTION"
    assert edge_data_comp[0]["is_junction_edge"] is True
    assert edge_data_comp[0]["active"] == "boolean"

    # Verify self-reference
    edge_data_self = graph.get_edge_data("employees", "employees")
    assert edge_data_self is not None
    assert edge_data_self[0]["label"] == "EMPLOYEES"
    assert edge_data_self[0]["is_junction_edge"] is False

    # Verify ODCS model is unmodified
    assert len(contract.schema_ or []) == original_schema_len


@pytest.fixture
def sample_graph_nary_junction_yaml_path() -> Path:
    return Path("tests/fixtures/contracts/odcs/graph_nary_junction.yaml")


def test_nary_junction_fallback(sample_graph_nary_junction_yaml_path):
    from semapact.utils.schema_utils import contract_to_model

    contract: OpenDataContractStandard = contract_to_model(
        sample_graph_nary_junction_yaml_path
    )
    builder = InMemoryGraphBuilder(contract)
    graph = builder.build()

    nodes = list(graph.nodes)

    # Check that N-ary junction fell back to standard node
    assert "user_project_role" in nodes

    # Ensure the edges from the N-ary junction are output correctly
    edge_data_users = graph.get_edge_data("users", "user_project_role")
    assert edge_data_users is not None
    assert edge_data_users[0]["label"] == "HAS_ROLE_IN"

    edge_data_projects = graph.get_edge_data("user_project_role", "projects")
    assert edge_data_projects is not None
    assert edge_data_projects[0]["label"] == "PROJECTS"

    edge_data_roles = graph.get_edge_data("user_project_role", "roles")
    assert edge_data_roles is not None
    assert edge_data_roles[0]["label"] == "ROLES"

    # Check that 1-ary junction fell back to standard node
    assert "one_ary_junction" in nodes

    edge_data_users_1ary = graph.get_edge_data("one_ary_junction", "users")
    assert edge_data_users_1ary is not None
    assert edge_data_users_1ary[0]["label"] == "USERS"


def test_builder_raises_on_invalid_input():
    with pytest.raises(ValueError):
        InMemoryGraphBuilder({"version": "1.0.0"})
