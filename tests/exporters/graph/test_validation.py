import pytest
import logging
from semapact.utils.schema_utils import contract_to_model

from semapact.exporters.graph_exporter import GraphNode, GraphEdge
from semapact.exporters.graph.validator import (
    TopologyValidator,
    TopologyValidationError,
)
from semapact.exporters.graph.interceptor import SovereigntyInterceptor


def test_topology_validator_success():
    validator = TopologyValidator()
    nodes = [
        GraphNode(name="users", type="Table"),
        GraphNode(name="users.id", id="users.id", type="Column"),
    ]
    edges = [GraphEdge(source="users", target="users.id", label="HAS_COLUMN")]

    report = validator.validate(nodes, edges)
    assert report.is_valid is True
    assert len(report.missing_inbound_edges) == 0


def test_topology_validator_missing_inbound_edge():
    validator = TopologyValidator()
    nodes = [
        GraphNode(name="users", type="Table"),
        GraphNode(name="users.id", id="users.id", type="Column"),
    ]
    edges = []  # No HAS_COLUMN edge

    with pytest.raises(TopologyValidationError) as exc:
        validator.validate(nodes, edges)

    assert "users.id" in str(exc.value)


def test_topology_validator_multiple_inbound_edges():
    validator = TopologyValidator()
    nodes = [
        GraphNode(name="users", type="Table"),
        GraphNode(name="users.id", id="users.id", type="Column"),
    ]
    edges = [
        GraphEdge(source="users", target="users.id", label="HAS_COLUMN"),
        GraphEdge(source="users", target="users.id", label="HAS_COLUMN"),
    ]

    with pytest.raises(TopologyValidationError) as exc:
        validator.validate(nodes, edges)

    assert "users.id" in str(exc.value)


def test_topology_validator_island_table(caplog):
    validator = TopologyValidator()
    nodes = [
        GraphNode(name="users", id="users", type="Table"),
        GraphNode(name="users.id", id="users.id", type="Column"),
        GraphNode(name="orders", id="orders", type="Table"),
    ]
    edges = [
        GraphEdge(source="users", target="users.id", label="HAS_COLUMN"),
    ]

    with caplog.at_level(logging.WARNING):
        report = validator.validate(nodes, edges)

    assert report.is_valid is True  # Islands are warnings, not errors
    assert "users" in report.island_tables
    assert "orders" in report.island_tables
    assert "absolute island" in caplog.text


def test_sovereignty_interceptor_schema_format():
    # Because interceptor now reads is_pii from the graph node directly,
    # we don't strictly need a full odcs model lookup anymore, but we can pass None or the actual model.
    # The interceptor signature takes contract: OpenDataContractStandard
    # Let's use the fixture just to be safe.
    contract = contract_to_model("tests/fixtures/contracts/odcs/graph_sample.yaml")

    nodes = [
        GraphNode(
            name="users.id",
            id="users.id",
            type="Column",
            properties={"is_pii": False, "example_value": "123"},
        ),
        GraphNode(
            name="users.email",
            id="users.email",
            type="Column",
            properties={"is_pii": True, "example_value": "test@example.com"},
        ),
    ]

    interceptor = SovereigntyInterceptor()
    interceptor.intercept(contract, nodes)

    # Check that ID was not redacted
    assert nodes[0].properties["example_value"] == "123"

    # Check that Email WAS redacted
    assert nodes[1].properties["example_value"] == "[REDACTED_PII]"
