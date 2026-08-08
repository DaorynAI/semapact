import argparse
from typing import Any

def run_lifecycle_promote(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.lifecycle_cli import apply_lifecycle
    return apply_lifecycle(args, is_promote=True)

def run_lifecycle_deprecate(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.core.lifecycle_cli import apply_lifecycle
    return apply_lifecycle(args, is_promote=False)
