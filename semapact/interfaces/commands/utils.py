import argparse
import os


def _resolve_adls_oauth_token_from_config() -> str | None:
    from semapact.core.config import config_manager
    auth_method = config_manager.get("azure.auth_method", "SEMAPACT_AZURE_AUTH_METHOD", "default").lower().strip()
    scope = config_manager.get("azure.scope", default="https://storage.azure.com/.default")

    try:
        from azure.identity import (
            ManagedIdentityCredential, 
            AzureCliCredential, 
            DefaultAzureCredential,
            EnvironmentCredential
        )
    except ImportError as exc:
        from semapact.exceptions import LifecycleError
        raise LifecycleError("azure-identity is required for ADLS OAuth auth.") from exc

    if auth_method in ("managedidentity", "msi", "managed_identity"):
        credential = ManagedIdentityCredential()
    elif auth_method in ("azurecli", "cli"):
        credential = AzureCliCredential()
    elif auth_method in ("environment", "env"):
        credential = EnvironmentCredential()
    else:
        credential = DefaultAzureCredential()
        
    return credential.get_token(scope).token


def _parse_table_uris(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None

def _build_git_config(args: argparse.Namespace):
    from semapact.devops.pr_creator import AzureDevOpsConfig, GitHubConfig
    from semapact.core.config import config_manager

    provider = getattr(args, "git_provider", None) or config_manager.get("git.provider", "SEMAPACT_GIT_PROVIDER", "azure")
    if provider == "github":
        return GitHubConfig(
            owner=getattr(args, "github_owner", None) or config_manager.get("git.github_owner", "SEMAPACT_GITHUB_OWNER", ""),
            repo=getattr(args, "github_repo", None) or config_manager.get("git.github_repo", "SEMAPACT_GITHUB_REPO", ""),
            token=getattr(args, "github_token", None) or config_manager.get("git.github_token", "SEMAPACT_GITHUB_TOKEN", ""),
        )
    return AzureDevOpsConfig(
        organization=getattr(args, "organization", None) or config_manager.get("git.organization", "SEMAPACT_ORGANIZATION", ""),
        project=getattr(args, "project", None) or config_manager.get("git.project", "SEMAPACT_PROJECT", ""),
        repository_id=getattr(args, "repository_id", None) or config_manager.get("git.repository_id", "SEMAPACT_REPOSITORY_ID", ""),
        pat_token=getattr(args, "pat_token", None) or config_manager.get("git.pat_token", "SEMAPACT_PAT_TOKEN", ""),
    )

def _get_repo_path(args: argparse.Namespace) -> str:
    if getattr(args, "repo_path", None):
        return args.repo_path

    gh_workspace = os.environ.get("GITHUB_WORKSPACE")
    if gh_workspace:
        return gh_workspace

    az_workspace = os.environ.get("BUILD_SOURCESDIRECTORY")
    if az_workspace:
        return az_workspace

    raise ValueError(
        "Could not determine repository path. Please provide --repo-path "
        "or set GITHUB_WORKSPACE / BUILD_SOURCESDIRECTORY environment variables."
    )
