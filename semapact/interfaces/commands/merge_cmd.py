import argparse
from pathlib import Path
from semapact.core.loader import ContractLoader
from semapact.governance import (
    GovernanceOperation,
    enforce_governance_gate,
    evaluate_governance_decision,
)
from semapact.lifecycle.merge_engine import ContractMergeEngine
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml

def run_merge(args: argparse.Namespace) -> Path:
    loader = ContractLoader(runtime_context=args.runtime_context)
    technical_source = loader.load(args.base)
    business_contract = loader.load(args.business)

    result = ContractMergeEngine().merge(
        technical_source,
        business_contract,
        fail_on_conflict=args.fail_on_conflict,
    )

    # Evaluate decision using business_contract as governed target base
    decision = evaluate_governance_decision(
        business_contract,
        result.contract,
        merge_conflicts=result.conflicts,
    )
    enforce_governance_gate(decision, GovernanceOperation.PROPOSE)

    return dump_yaml(contract_to_dict(result.contract), args.output)
