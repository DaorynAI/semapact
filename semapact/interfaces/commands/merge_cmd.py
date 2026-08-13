import argparse
from pathlib import Path

from semapact.core.loader import ContractLoader
from semapact.governance import GovernanceOperation, enforce_governance_gate
from semapact.services import GovernanceService
from semapact.utils.schema_utils import contract_to_dict
from semapact.utils.yaml_utils import dump_yaml


def run_merge(args: argparse.Namespace) -> Path:
    loader = ContractLoader(runtime_context=args.runtime_context)
    technical_source = loader.load(args.base)
    business_contract = loader.load(args.business)

    analysis = GovernanceService().merge_and_evaluate(
        technical_source,
        business_contract,
        effective_date=args.effective_date,
        fail_on_conflict=False,
    )
    enforce_governance_gate(analysis.decision, GovernanceOperation.PROPOSE)

    return dump_yaml(contract_to_dict(analysis.merge_result.contract), args.output)
