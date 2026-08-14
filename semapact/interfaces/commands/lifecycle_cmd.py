import argparse
from typing import Any

from semapact.services import GovernanceService


def run_lifecycle_promote(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.lifecycle_cli import apply_lifecycle

    context = GovernanceService.create_context(args.effective_date)
    return apply_lifecycle(args, is_promote=True, context=context)


def run_lifecycle_deprecate(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.lifecycle_cli import apply_lifecycle

    context = GovernanceService.create_context(args.effective_date)
    return apply_lifecycle(args, is_promote=False, context=context)
