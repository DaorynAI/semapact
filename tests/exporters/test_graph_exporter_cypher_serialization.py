from semapact.exporters.graph_exporter import CypherSerializer, GraphNode


def test_cypher_serializer_escaping():
    serializer = CypherSerializer()
    properties = {
        "desc1": "It has 'single quotes'",
        "desc2": 'It has "double quotes"',
        "desc3": "It has \n newlines",
        "nested": {"key": "value"},
        "list_prop": ["a", "b"],
    }
    nodes = [GraphNode(name="Test", type="Table", properties=properties)]
    result = serializer.serialize(nodes, [])

    assert "desc1: \"It has 'single quotes'\"" in result
    assert 'desc2: "It has \\"double quotes\\""' in result
    assert 'desc3: "It has \\n newlines"' in result
    assert 'nested: "{\\"key\\": \\"value\\"}"' in result
    assert 'list_prop: "[\\"a\\", \\"b\\"]"' in result
