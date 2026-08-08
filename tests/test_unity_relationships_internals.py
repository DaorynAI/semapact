from __future__ import annotations

from semapact.importers.unity_relationships import _constraint_items


def test_constraint_items_empty_metadata():
    assert _constraint_items({}) == []


def test_constraint_items_supported_keys():
    metadata = {
        "table_constraints": [{"id": 1}],
        "tableConstraints": [{"id": 2}],
        "constraints": [{"id": 3}],
        "foreign_keys": [{"id": 4}],
        "foreignKeys": [{"id": 5}],
    }
    result = _constraint_items(metadata)
    assert len(result) == 5
    assert {"id": 1} in result
    assert {"id": 2} in result
    assert {"id": 3} in result
    assert {"id": 4} in result
    assert {"id": 5} in result


def test_constraint_items_ignores_non_list_values():
    metadata = {"table_constraints": "not a list", "constraints": [{"id": 1}]}
    assert _constraint_items(metadata) == [{"id": 1}]


def test_constraint_items_filters_non_dict_items():
    metadata = {"constraints": [{"id": 1}, "not a dict", 123, None]}
    assert _constraint_items(metadata) == [{"id": 1}]


def test_constraint_items_mixed_keys():
    metadata = {"tableConstraints": [{"id": 1}], "foreign_keys": [{"id": 2}]}
    result = _constraint_items(metadata)
    assert len(result) == 2
    assert {"id": 1} in result
    assert {"id": 2} in result
