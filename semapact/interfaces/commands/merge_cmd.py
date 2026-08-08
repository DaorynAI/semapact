import argparse
from pathlib import Path

def run_merge(args: argparse.Namespace) -> Path:
    from semapact.core.loader import ContractLoader
    from semapact.lifecycle.merge_engine import ContractMergeEngine
    from semapact.utils.schema_utils import contract_to_dict
    from semapact.utils.yaml_utils import dump_yaml

    loader = ContractLoader(runtime_context=args.runtime_context)
    base_contract = loader.load(args.base)
    business_contract = loader.load(args.business)

    result = ContractMergeEngine().merge(
        base_contract,
        business_contract,
        fail_on_conflict=args.fail_on_conflict,
    )
    return dump_yaml(contract_to_dict(result.contract), args.output)
