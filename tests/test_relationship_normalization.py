from semapact.lifecycle.policy import evaluate_merge_policy
from semapact.lifecycle.relationships import (
    normalize_endpoint_value,
    normalize_relationship_endpoint,
)


def test_normalize_relationship_endpoint_scalar():
    assert normalize_relationship_endpoint("  Users.ID  ") == "users.id"
    assert normalize_relationship_endpoint("orders.user_id") == "orders.user_id"
    assert normalize_relationship_endpoint(None) == ""


def test_normalize_endpoint_value_composite_preserves_order():
    assert normalize_endpoint_value([" Users.id ", " Orders.user_id "]) == "users.id,orders.user_id"
    assert normalize_endpoint_value([" Orders.user_id ", " Users.id "]) == "orders.user_id,users.id"
    assert normalize_endpoint_value(["a", "b"]) != normalize_endpoint_value(["b", "a"])


def test_relationship_endpoint_case_whitespace_normalization(relationship_base_contract_model):
    relationship_base_contract_model.status = "active"
    target = relationship_base_contract_model.model_copy(deep=True)
    target.status = "active"
    assert target.schema_ is not None
    assert target.schema_[1].properties is not None
    assert target.schema_[1].properties[0].relationships is not None
    target.schema_[1].properties[0].relationships[0].to = "  Users.ID  "

    evaluation = evaluate_merge_policy(relationship_base_contract_model, target)
    assert evaluation.valid is True
    assert evaluation.breaking_changes == []
