"""Tests for PublicGovernanceDecisionV1 schema, projection, serialization, and golden fixtures."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import pytest
from pydantic import ValidationError as PydanticValidationError
from open_data_contract_standard.model import (
    CustomProperty,
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

from semapact.change_context import ChangeContext
from semapact.governance import (
    PublicChangeContextV1,
    PublicChangeEvidenceV1,
    PublicGovernanceChangeEvidenceV1,
    PublicGovernanceChangeV1,
    PublicGovernanceDecisionV1,
    PublicGovernanceReasonV1,
    PublicPolicyOutcomeV1,
    PublicValidationOutcomeV1,
    evaluate_governance_decision,
    serialize_public_governance_decision,
    to_public_governance_decision,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "governance_decisions"
TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))


def _get_schemas(contract: OpenDataContractStandard) -> list[SchemaObject]:
    return getattr(contract, "schema_", getattr(contract, "schema", [])) or []


def _make_contract(
    contract_id: str = "my-data-contract",
    version: str = "1.0.0",
    status: str = "active",
    properties: list[SchemaProperty] | None = None,
) -> OpenDataContractStandard:
    if properties is None:
        properties = [
            SchemaProperty(
                name="id",
                logicalType="string",
                physicalType="varchar(255)",
                required=True,
            ),
            SchemaProperty(
                name="amount",
                logicalType="number",
                physicalType="decimal(10,2)",
                required=False,
            ),
        ]
    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id=contract_id,
        name=contract_id,
        version=version,
        status=status,
        schema=[
            SchemaObject(
                name="orders",
                physicalName="orders",
                properties=properties,
            )
        ],
    )


def test_public_decision_allow_scenario():
    """Identical active contracts produce ALLOW decision with clean public projection."""
    base = _make_contract()
    candidate = _make_contract()

    decision = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    assert isinstance(public_dec, PublicGovernanceDecisionV1)
    assert public_dec.schema_version == "1"
    assert public_dec.decision == "ALLOW"
    assert public_dec.contract_id == "my-data-contract"
    assert public_dec.breaking is False
    assert public_dec.required_version_bump == "none"
    assert public_dec.context.effective_date == "2026-01-01"
    assert public_dec.validation.valid is True
    assert public_dec.policy.valid is True
    assert public_dec.policy.id_violation is False
    assert public_dec.policy.version_violation is False
    assert public_dec.policy.retired_violation is False
    assert public_dec.evidence.has_changes is False
    assert public_dec.evidence.merge_conflicts_count == 0
    assert len(public_dec.reasons) == 1
    assert public_dec.reasons[0].code == "CHANGE_ASSESSMENT"
    assert public_dec.reasons[0].severity == "INFO"
    assert len(public_dec.changes) == 0
    assert public_dec.reason_codes == ("CHANGE_ASSESSMENT",)

    # Verify camelCase serialization
    dumped = public_dec.to_canonical_dict()
    assert dumped["schemaVersion"] == "1"
    assert dumped["decisionId"] == decision.decision_id
    assert dumped["contractId"] == "my-data-contract"
    assert dumped["context"] == {"effectiveDate": "2026-01-01"}
    assert dumped["requiredVersionBump"] == "none"
    assert dumped["evidence"] == {"hasChanges": False, "mergeConflictsCount": 0}
    assert dumped["changes"] == []
    assert dumped["reasonCodes"] == ["CHANGE_ASSESSMENT"]


def test_public_decision_review_scenario():
    """Deprecating a property in an active contract produces a valid REVIEW public decision."""
    base = _make_contract()
    cand = _make_contract()
    _get_schemas(cand)[0].properties[1].customProperties = [
        CustomProperty(property="lifecycleStatus", value="deprecated")
    ]

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    assert public_dec.schema_version == "1"
    assert public_dec.decision == "REVIEW"
    assert public_dec.breaking is False
    assert public_dec.required_version_bump == "minor"
    assert public_dec.evidence.has_changes is True
    assert len(public_dec.changes) > 0

    # Ensure reasonCodes contains sorted unique code identifiers
    assert "CHANGE_ASSESSMENT" in public_dec.reason_codes

    # Ensure canonical change contains camelCase and proper fields
    dumped = public_dec.to_canonical_dict()
    first_change = dumped["changes"][0]
    assert "changeType" in first_change
    assert "entityType" in first_change
    assert "domain" in first_change
    assert "reasonCodes" in first_change
    assert "identity" in first_change


def test_public_decision_breaking_review_scenario():
    """Decimal precision reduction in active contract produces REVIEW decision with major bump and breaking=True."""
    base = _make_contract()
    cand = _make_contract()
    _get_schemas(cand)[0].properties[1].physicalType = "decimal(8,2)"

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    assert public_dec.schema_version == "1"
    assert public_dec.decision == "REVIEW"
    assert public_dec.breaking is True
    assert public_dec.required_version_bump == "major"
    assert public_dec.reason_codes == ("CHANGE_ASSESSMENT", "DECIMAL_PRECISION_REDUCED")

    dumped = public_dec.to_canonical_dict()
    assert dumped["decision"] == "REVIEW"
    assert dumped["breaking"] is True
    assert dumped["requiredVersionBump"] == "major"
    assert any(r["code"] == "DECIMAL_PRECISION_REDUCED" for r in dumped["reasons"])


def test_public_decision_block_retired_scenario():
    """Modifying retired contract produces BLOCK decision with RETIRED_CONTRACT_MODIFIED."""
    base = _make_contract(status="retired")
    cand = _make_contract(status="retired")
    _get_schemas(cand)[0].properties[1].description = "New description"

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    assert public_dec.decision == "BLOCK"
    assert public_dec.policy.valid is False
    assert public_dec.policy.retired_violation is True
    assert "RETIRED_CONTRACT_MODIFIED" in public_dec.reason_codes

    dumped = public_dec.to_canonical_dict()
    assert dumped["policy"]["retiredViolation"] is True


def test_public_decision_block_validation_scenario():
    """Invalid candidate schema property causes BLOCK decision with VALIDATION_FAILED."""
    base = _make_contract()
    cand = _make_contract()
    _get_schemas(cand)[0].properties.append(
        SchemaProperty(name="", logicalType="string", physicalType="", required=True)
    )

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    assert public_dec.decision == "BLOCK"
    assert public_dec.validation.valid is False
    assert "VALIDATION_FAILED" in public_dec.reason_codes

    dumped = public_dec.to_canonical_dict()
    assert dumped["decision"] == "BLOCK"
    assert dumped["validation"]["valid"] is False


def test_public_models_direct_instantiation_and_helpers():
    """Verify direct instantiation of public models and helper structures."""
    context = PublicChangeContextV1(effective_date="2026-08-28")
    reason = PublicGovernanceReasonV1(
        code="TEST_CODE",
        severity="WARNING",
        message="A test warning",
        path="schema.orders",
        details={"key": "val"},
    )
    validation = PublicValidationOutcomeV1(valid=True, issues=(reason,))
    policy = PublicPolicyOutcomeV1(valid=True, violations=())
    evidence = PublicChangeEvidenceV1(has_changes=True, merge_conflicts_count=1)
    ev_source = PublicGovernanceChangeEvidenceV1(source="MERGE_CONFLICT", code="conflict")
    change = PublicGovernanceChangeV1(
        change_type="MODIFY",
        entity_type="PROPERTY",
        identity=("orders", "amount"),
        path="schema[orders].properties[amount]",
        field="physicalType",
        before="decimal(10,2)",
        after="decimal(8,2)",
        domain="STRUCTURE",
        breaking=True,
        reason_codes=("DECIMAL_PRECISION_REDUCED",),
        evidence=(ev_source,),
    )

    decision = PublicGovernanceDecisionV1(
        schema_version="1",
        decision_id="00000000-0000-0000-0000-000000000000",
        decision="REVIEW",
        contract_id="orders",
        context=context,
        breaking=True,
        required_version_bump="major",
        reason_codes=("DECIMAL_PRECISION_REDUCED",),
        reasons=(reason,),
        validation=validation,
        policy=policy,
        evidence=evidence,
        changes=(change,),
    )

    assert decision.context.effective_date == "2026-08-28"
    assert decision.changes[0].evidence[0].source == "MERGE_CONFLICT"
    assert decision.changes[0].field == "physicalType"
    assert decision.validation.issues[0].details == {"key": "val"}


def test_public_literals_strict_validation():
    """Verify that invalid strings for protocol literals are rejected at validation."""
    with pytest.raises(PydanticValidationError):
        PublicGovernanceDecisionV1.model_validate({
            "schemaVersion": "1",
            "decisionId": "test",
            "decision": "BANANA",  # Invalid decision
            "contractId": "orders",
            "context": {"effectiveDate": "2026-01-01"},
            "breaking": False,
            "requiredVersionBump": "none",
            "reasonCodes": [],
            "reasons": [],
            "validation": {"valid": True, "issues": []},
            "policy": {"valid": True, "idViolation": False, "versionViolation": False, "retiredViolation": False, "violations": []},
            "evidence": {"hasChanges": False, "mergeConflictsCount": 0},
            "changes": [],
        })

    with pytest.raises(PydanticValidationError):
        PublicGovernanceDecisionV1.model_validate({
            "schemaVersion": "1",
            "decisionId": "test",
            "decision": "ALLOW",
            "contractId": "orders",
            "context": {"effectiveDate": "2026-01-01"},
            "breaking": False,
            "requiredVersionBump": "huge",  # Invalid bump
            "reasonCodes": [],
            "reasons": [],
            "validation": {"valid": True, "issues": []},
            "policy": {"valid": True, "idViolation": False, "versionViolation": False, "retiredViolation": False, "violations": []},
            "evidence": {"hasChanges": False, "mergeConflictsCount": 0},
            "changes": [],
        })


def test_public_decision_immutability_and_extra_forbid():
    """Public governance models are frozen and reject extra fields."""
    base = _make_contract()
    decision = evaluate_governance_decision(base, base, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    # Immutability
    with pytest.raises((PydanticValidationError, TypeError)):
        public_dec.decision = "BLOCK"  # type: ignore

    # Extra forbid
    with pytest.raises(PydanticValidationError):
        PublicGovernanceDecisionV1.model_validate({
            "schemaVersion": "1",
            "decisionId": "test",
            "decision": "ALLOW",
            "contractId": "orders",
            "context": {"effectiveDate": "2026-01-01"},
            "breaking": False,
            "requiredVersionBump": "none",
            "reasonCodes": [],
            "reasons": [],
            "validation": {"valid": True, "issues": []},
            "policy": {"valid": True, "idViolation": False, "versionViolation": False, "retiredViolation": False, "violations": []},
            "evidence": {"hasChanges": False, "mergeConflictsCount": 0},
            "changes": [],
            "unknown_extra_field": 123,
        })


def test_public_decision_byte_level_determinism():
    """Semantically equivalent states with differing incidental ordering produce byte-for-byte identical canonical JSON."""
    # Decision 1
    reason1 = PublicGovernanceReasonV1(
        code="RULE_VIOLATION",
        severity="WARNING",
        message="Message",
        details={"zebra": 1, "apple": 2, "mango": 3},
    )
    change1 = PublicGovernanceChangeV1(
        change_type="MODIFY",
        entity_type="PROPERTY",
        identity=("orders", "amount"),
        path="schema[orders].properties[amount]",
        domain="STRUCTURE",
        breaking=True,
        reason_codes=("Z_CODE", "A_CODE"),
    )
    dec1 = PublicGovernanceDecisionV1(
        schema_version="1",
        decision_id="11111111-1111-1111-1111-111111111111",
        decision="REVIEW",
        contract_id="orders",
        context=PublicChangeContextV1(effective_date="2026-01-01"),
        breaking=True,
        required_version_bump="major",
        reason_codes=("Z_CODE", "A_CODE"),
        reasons=(reason1,),
        validation=PublicValidationOutcomeV1(valid=True),
        policy=PublicPolicyOutcomeV1(valid=True),
        evidence=PublicChangeEvidenceV1(has_changes=True),
        changes=(change1,),
    )

    # Decision 2 with different key insertion order in details
    reason2 = PublicGovernanceReasonV1(
        code="RULE_VIOLATION",
        severity="WARNING",
        message="Message",
        details={"mango": 3, "apple": 2, "zebra": 1},
    )
    dec2 = PublicGovernanceDecisionV1(
        schema_version="1",
        decision_id="11111111-1111-1111-1111-111111111111",
        decision="REVIEW",
        contract_id="orders",
        context=PublicChangeContextV1(effective_date="2026-01-01"),
        breaking=True,
        required_version_bump="major",
        reason_codes=("Z_CODE", "A_CODE"),
        reasons=(reason2,),
        validation=PublicValidationOutcomeV1(valid=True),
        policy=PublicPolicyOutcomeV1(valid=True),
        evidence=PublicChangeEvidenceV1(has_changes=True),
        changes=(change1,),
    )

    json1 = serialize_public_governance_decision(dec1, indent=2)
    json2 = serialize_public_governance_decision(dec2, indent=2)

    assert json1 == json2
    assert json1.encode("utf-8") == json2.encode("utf-8")


def test_public_decision_roundtrip_deserialization():
    """PublicGovernanceDecisionV1 can deserialize from camelCase JSON and equals original."""
    base = _make_contract()
    cand = _make_contract()
    _get_schemas(cand)[0].properties[1].physicalType = "decimal(8,2)"

    decision = evaluate_governance_decision(base, cand, context=TEST_CONTEXT)
    public_dec = to_public_governance_decision(decision)

    json_str = serialize_public_governance_decision(public_dec)
    restored = PublicGovernanceDecisionV1.model_validate_json(json_str)

    assert restored == public_dec
    assert restored.decision_id == public_dec.decision_id
    assert restored.decision == "REVIEW"
    assert restored.schema_version == "1"


def test_golden_fixtures_match():
    """Verify golden JSON fixtures match projected decisions with exact string equality (read-only assertion)."""
    # 1. ALLOW clean
    base = _make_contract()
    allow_dec = evaluate_governance_decision(base, base, context=TEST_CONTEXT)
    allow_pub = to_public_governance_decision(allow_dec)
    allow_json_str = serialize_public_governance_decision(allow_pub, indent=2) + "\n"
    expected_allow = (FIXTURES_DIR / "allow_clean_decision.json").read_text(encoding="utf-8")
    assert allow_json_str == expected_allow

    # 2. BREAKING review decimal
    cand_breaking = _make_contract()
    _get_schemas(cand_breaking)[0].properties[1].physicalType = "decimal(8,2)"
    breaking_dec = evaluate_governance_decision(base, cand_breaking, context=TEST_CONTEXT)
    breaking_pub = to_public_governance_decision(breaking_dec)
    breaking_json_str = serialize_public_governance_decision(breaking_pub, indent=2) + "\n"
    expected_breaking = (FIXTURES_DIR / "breaking_review_decision.json").read_text(encoding="utf-8")
    assert breaking_json_str == expected_breaking

    # 3. REVIEW deprecate property
    cand_deprecate = _make_contract()
    _get_schemas(cand_deprecate)[0].properties[1].customProperties = [
        CustomProperty(property="lifecycleStatus", value="deprecated")
    ]
    review_dec = evaluate_governance_decision(base, cand_deprecate, context=TEST_CONTEXT)
    review_pub = to_public_governance_decision(review_dec)
    review_json_str = serialize_public_governance_decision(review_pub, indent=2) + "\n"
    expected_review = (FIXTURES_DIR / "review_deprecate_decision.json").read_text(encoding="utf-8")
    assert review_json_str == expected_review

    # 4. BLOCK retired contract
    base_retired = _make_contract(status="retired")
    cand_retired = _make_contract(status="retired")
    _get_schemas(cand_retired)[0].properties[1].description = "Retired update"
    retired_dec = evaluate_governance_decision(base_retired, cand_retired, context=TEST_CONTEXT)
    retired_pub = to_public_governance_decision(retired_dec)
    retired_json_str = serialize_public_governance_decision(retired_pub, indent=2) + "\n"
    expected_retired = (FIXTURES_DIR / "block_retired_decision.json").read_text(encoding="utf-8")
    assert retired_json_str == expected_retired

    # 5. BLOCK invalid validation
    cand_invalid = _make_contract()
    _get_schemas(cand_invalid)[0].properties.append(
        SchemaProperty(name="", logicalType="string", physicalType="", required=True)
    )
    invalid_dec = evaluate_governance_decision(base, cand_invalid, context=TEST_CONTEXT)
    invalid_pub = to_public_governance_decision(invalid_dec)
    invalid_json_str = serialize_public_governance_decision(invalid_pub, indent=2) + "\n"
    expected_invalid = (FIXTURES_DIR / "block_validation_decision.json").read_text(encoding="utf-8")
    assert invalid_json_str == expected_invalid
