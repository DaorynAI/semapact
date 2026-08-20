"""Tests for the stable GovernanceDecision V1 machine-readable contract."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from semapact.change_context import ChangeContext
from semapact.governance import (
    ChangeEvidence,
    DecisionResult,
    GovernanceDecision,
    GovernanceReason,
    PolicyOutcome,
    ValidationOutcome,
    governance_decision_json_schema,
    governance_decision_payload_to_json,
    governance_decision_to_dict,
    governance_decision_to_json,
    parse_governance_decision_json,
)
from semapact.governance_codes import GovernanceReasonCode, GovernanceSeverity
from semapact.lifecycle.changes import (
    GovernanceChange,
    GovernanceChangeDomain,
    GovernanceChangeType,
    GovernanceEntityType,
)
from semapact.orchestrator.pipeline import _build_manifest_payload

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "governance_decision" / "v1"


def _allow_decision() -> GovernanceDecision:
    return GovernanceDecision(
        decision_id="decision-allow-001",
        decision=DecisionResult.ALLOW,
        contract_id="urn:datacontract:orders",
        context=ChangeContext(effective_date=date(2026, 8, 20)),
        breaking=False,
        required_version_bump="none",
        validation=ValidationOutcome(valid=True),
        policy=PolicyOutcome(valid=True),
        evidence=ChangeEvidence(has_changes=False, merge_conflicts_count=0),
    )


def _block_decision() -> GovernanceDecision:
    reason = GovernanceReason(
        code=GovernanceReasonCode.PROPERTY_REMOVED,
        message="Property was removed.",
        path="schema[orders].properties[legacy_id]",
        severity=GovernanceSeverity.WARNING,
        details={"internalOnly": "must-not-leak"},
    )
    change = GovernanceChange(
        change_type=GovernanceChangeType.REMOVE,
        entity_type=GovernanceEntityType.PROPERTY,
        identity=("orders", "legacy_id"),
        path="schema[orders].properties[legacy_id]",
        field=None,
        before={"name": "legacy_id", "logicalType": "string"},
        after=None,
        domain=GovernanceChangeDomain.STRUCTURE,
        breaking=True,
        reason_codes=(GovernanceReasonCode.PROPERTY_REMOVED,),
    )
    return GovernanceDecision(
        decision_id="decision-block-001",
        decision=DecisionResult.BLOCK,
        contract_id="urn:datacontract:orders",
        context=ChangeContext(effective_date=date(2026, 8, 20)),
        breaking=True,
        required_version_bump="major",
        validation=ValidationOutcome(valid=True),
        policy=PolicyOutcome(valid=False, violations=(reason,)),
        evidence=ChangeEvidence(has_changes=True, merge_conflicts_count=0),
        reasons=(reason,),
        changes=(change,),
    )


def test_allow_decision_matches_canonical_golden_fixture() -> None:
    expected = (FIXTURE_DIR / "allow_no_change.json").read_text(encoding="utf-8")
    assert governance_decision_to_json(_allow_decision()) == expected


def test_block_decision_matches_canonical_golden_fixture() -> None:
    expected = (FIXTURE_DIR / "block_property_removed.json").read_text(encoding="utf-8")
    assert governance_decision_to_json(_block_decision()) == expected


def test_v1_payload_round_trip_is_byte_equivalent() -> None:
    canonical = governance_decision_to_json(_block_decision())
    payload = parse_governance_decision_json(canonical)
    assert governance_decision_payload_to_json(payload) == canonical


def test_public_contract_uses_stable_aliases_and_excludes_internal_details() -> None:
    payload = governance_decision_to_dict(_block_decision())

    assert payload["schemaVersion"] == "1"
    assert payload["decisionId"] == "decision-block-001"
    assert payload["contractId"] == "urn:datacontract:orders"
    assert payload["effectiveDate"] == "2026-08-20"
    assert payload["requiredVersionBump"] == "major"
    assert payload["reasonCodes"] == ["PROPERTY_REMOVED"]
    assert "decision_id" not in payload
    assert "context" not in payload
    assert "breaking_changes" not in payload["policy"]
    assert "details" not in payload["reasons"][0]


def test_lists_and_optional_fields_have_fixed_shapes() -> None:
    allow_payload = governance_decision_to_dict(_allow_decision())
    assert allow_payload["reasonCodes"] == []
    assert allow_payload["reasons"] == []
    assert allow_payload["changes"] == []
    assert allow_payload["validation"]["issueCodes"] == []
    assert allow_payload["validation"]["issues"] == []

    block_payload = governance_decision_to_dict(_block_decision())
    assert block_payload["changes"][0]["field"] is None
    assert block_payload["changes"][0]["after"] is None
    assert block_payload["changes"][0]["evidence"] == []


def test_json_schema_uses_public_field_names_and_v1_version() -> None:
    schema = governance_decision_json_schema()
    properties = schema["properties"]

    assert "schemaVersion" in properties
    assert "decisionId" in properties
    assert "contractId" in properties
    assert "effectiveDate" in properties
    assert "requiredVersionBump" in properties
    assert "decision_id" not in properties
    assert properties["schemaVersion"]["const"] == "1"


def test_pipeline_manifest_embeds_public_v1_contract() -> None:
    manifest = _build_manifest_payload(_block_decision())
    decision = manifest["governanceDecision"]

    assert decision["schemaVersion"] == "1"
    assert decision["decisionId"] == "decision-block-001"
    assert "decision_id" not in decision
    assert "context" not in decision
