"""Regression tests for CI governance projections and side-effect gating."""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.exceptions import GovernanceReviewRequiredError
from semapact.governance import ChangeContext, enforce_governance_gate
from semapact.governance.evaluator import evaluate_governance_decision
from semapact.lifecycle.merge_engine import MergeResult
from semapact.orchestrator.pipeline import ContractPipeline, _build_manifest_payload


TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))


def _make_contract(*, include_amount: bool = True, include_note: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        )
    ]
    if include_amount:
        properties.append(
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,2)",
                required=False,
            )
        )
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                logicalType="string",
                physicalType="varchar(100)",
                required=False,
            )
        )

    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders",
        name="orders",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def test_manifest_breaking_changes_project_authoritative_decision() -> None:
    """Legacy manifest projection must mirror decision policy evidence exactly."""
    base = _make_contract(include_amount=True)
    candidate = _make_contract(include_amount=False)

    decision = evaluate_governance_decision(
        base,
        candidate,
        context=TEST_CONTEXT,
    )
    decision_payload = decision.model_dump(mode="json")
    manifest = _build_manifest_payload(decision)

    expected_breaking_changes = decision_payload["policy"]["breaking_changes"]
    assert decision.breaking is True
    assert expected_breaking_changes
    assert manifest["breakingChanges"] == expected_breaking_changes
    assert {item["code"] for item in manifest["breakingChanges"]} == {
        "PROPERTY_REMOVED"
    }
    assert "POLICY_BREAKING_CHANGE" not in str(manifest)


def test_manifest_non_breaking_change_has_no_breaking_projection() -> None:
    """A reviewable additive change must not invent breaking-change evidence."""
    base = _make_contract()
    candidate = _make_contract(include_note=True)

    decision = evaluate_governance_decision(
        base,
        candidate,
        context=TEST_CONTEXT,
    )
    manifest = _build_manifest_payload(decision)

    assert decision.breaking is False
    assert manifest["breakingChanges"] == []


def test_pipeline_enforces_ci_gate_once_at_side_effect_boundary(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline writes decision evidence, then delegates one CI gate to artifact preparation."""
    base = _make_contract()
    candidate = _make_contract(include_note=True)
    pipeline = ContractPipeline()

    monkeypatch.setattr(
        ContractPipeline,
        "import_schema",
        lambda *args, **kwargs: candidate,
    )
    monkeypatch.setattr(
        type(pipeline.loader),
        "load",
        lambda self, path: base,
    )
    monkeypatch.setattr(
        ContractPipeline,
        "merge_contract_updates",
        lambda *args, **kwargs: MergeResult(contract=candidate, conflicts=[]),
    )

    manifest_path = tmp_path / "ci_manifest.json"
    merged_path = tmp_path / "merged.yaml"
    ge_path = tmp_path / "suite.json"

    with mock.patch(
        "semapact.orchestrator.pipeline.enforce_governance_gate",
        wraps=enforce_governance_gate,
    ) as gate_spy:
        with pytest.raises(GovernanceReviewRequiredError):
            pipeline.run(
                source_type="sql",
                source="ignored",
                business_contract_path="ignored",
                merged_contract_output_path=str(merged_path),
                ge_suite_output_path=str(ge_path),
                ci_manifest_output_path=str(manifest_path),
                change_context=TEST_CONTEXT,
            )

    assert gate_spy.call_count == 1
    assert manifest_path.exists()
    assert not merged_path.exists()
    assert not ge_path.exists()
