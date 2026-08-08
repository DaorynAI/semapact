import argparse
from typing import Any
from semapact.interfaces.commands.utils import _build_git_config, _get_repo_path

def run_create_pr(args: argparse.Namespace) -> dict[str, Any]:
    from semapact.devops.pr_creator import PullRequestCreator

    config = _build_git_config(args)
    manager = PullRequestCreator(config=config)
    return manager.create_update_pr(
        repo_path=_get_repo_path(args),
        source_branch=args.source_branch,
        target_branch=args.target_branch,
        commit_message=args.commit_message,
        title=args.title,
        description=args.description,
        paths=args.paths,
        push=args.push,
    )
