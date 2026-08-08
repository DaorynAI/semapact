from __future__ import annotations

import base64
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import logging
import requests

LOGGER = logging.getLogger(__name__)


def _get_git_config(repo_path: str | None, key: str) -> str | None:
    try:
        actual_repo_path = repo_path or str(Path.cwd())
        result = subprocess.run(
            ["git", "-C", actual_repo_path, "config", "--local", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        LOGGER.debug(f"Failed to get git config {key}: {e}")
    return None


def _set_git_config(repo_path: str | None, key: str, value: str) -> None:
    try:
        actual_repo_path = repo_path or str(Path.cwd())
        subprocess.run(
            ["git", "-C", actual_repo_path, "config", "--local", key, value], check=True
        )
    except Exception as e:
        LOGGER.debug(f"Failed to set git config {key}: {e}")


class GitProviderConfig(Protocol):
    """Protocol for Git provider configuration."""

    pass


@dataclass(slots=True)
class AzureDevOpsConfig:
    """Azure DevOps connection settings."""

    organization: str
    project: str
    repository_id: str
    pat_token: str
    api_version: str = "7.1-preview.1"


@dataclass(slots=True)
class GitHubConfig:
    """GitHub connection settings."""

    owner: str
    repo: str
    token: str


class GitProvider(Protocol):
    """Protocol for Git provider operations."""

    def create_pull_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]: ...


class AzureDevOpsProvider:
    def __init__(self, config: AzureDevOpsConfig):
        self.config = config

    def create_pull_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Create an Azure DevOps pull request, prioritizing CLI then falling back to REST API."""
        method_override = os.environ.get("SEMAPACT_PR_METHOD")

        if method_override == "api":
            return self._create_pull_request_api(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
            )

        if method_override == "cli":
            return self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
            )

        # Fallback chain with caching
        cache_key = "semapact.pr-auth-method"
        cached_method = _get_git_config(repo_path, cache_key) if repo_path else None

        if cached_method == "cli":
            try:
                return self._create_pull_request_cli(
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    description=description,
                    reviewers=reviewers,
                    repo_path=repo_path,
                )
            except Exception as e:
                LOGGER.debug(f"Cached CLI method failed: {e}")
                if repo_path:
                    _set_git_config(repo_path, cache_key, "")

        if cached_method == "api":
            try:
                return self._create_pull_request_api(
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    description=description,
                    reviewers=reviewers,
                )
            except Exception as e:
                LOGGER.debug(f"Cached API method failed: {e}")
                if repo_path:
                    _set_git_config(repo_path, cache_key, "")

        # 1. Native CLI
        try:
            result = self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
            )
            if repo_path:
                _set_git_config(repo_path, cache_key, "cli")
            return result
        except Exception as e:
            LOGGER.debug(f"Native CLI PR creation failed: {e}")

        # 2. CLI with token
        try:
            result = self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
                inject_token=True,
            )
            if repo_path:
                _set_git_config(repo_path, cache_key, "cli")
            return result
        except Exception as e:
            LOGGER.debug(f"CLI with token PR creation failed: {e}")

        # 3. API Fallback
        result = self._create_pull_request_api(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            reviewers=reviewers,
        )
        if repo_path:
            _set_git_config(repo_path, cache_key, "api")
        return result

    def _create_pull_request_cli(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
        inject_token: bool = False,
    ) -> dict[str, Any]:
        if not repo_path:
            raise RuntimeError("repo_path is required for CLI PR creation")

        if source_branch.startswith("-") or target_branch.startswith("-"):
            raise ValueError(f"Invalid branch name: {source_branch} or {target_branch}. Branch names cannot start with a hyphen.")

        cmd = [
            "az",
            "repos",
            "pr",
            "create",
            "--source-branch",
            source_branch,
            "--target-branch",
            target_branch,
            "--title",
            title,
            "--description",
            description,
            "--output",
            "json",
        ]

        if reviewers:
            cmd.extend(["--reviewers", *reviewers])

        env = os.environ.copy()
        if inject_token:
            env["AZURE_DEVOPS_EXT_PAT"] = self.config.pat_token

        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create PR in Azure DevOps via CLI: {result.stderr}"
            )

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw_output": result.stdout}

    def _create_pull_request_api(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an Azure DevOps pull request via REST API."""
        url = (
            f"https://dev.azure.com/{self.config.organization}/{self.config.project}"
            f"/_apis/git/repositories/{self.config.repository_id}/pullrequests"
            f"?api-version={self.config.api_version}"
        )

        payload: dict[str, Any] = {
            "sourceRefName": f"refs/heads/{source_branch}",
            "targetRefName": f"refs/heads/{target_branch}",
            "title": title,
            "description": description,
        }
        if reviewers:
            payload["reviewers"] = [{"id": reviewer} for reviewer in reviewers]

        response = requests.post(
            url, headers=self._headers(), data=json.dumps(payload), timeout=30
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to create PR in Azure DevOps: status={response.status_code}, body={response.text[:500]}"
            )
        return response.json()

    def _headers(self) -> dict[str, str]:
        token = f":{self.config.pat_token}".encode("utf-8")
        auth = base64.b64encode(token).decode("utf-8")
        return {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }


class GitHubProvider:
    def __init__(self, config: GitHubConfig):
        self.config = config

    def create_pull_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub pull request, prioritizing CLI then falling back to REST API."""
        method_override = os.environ.get("SEMAPACT_PR_METHOD")

        if method_override == "api":
            return self._create_pull_request_api(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
            )

        if method_override == "cli":
            return self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
            )

        # Fallback chain with caching
        cache_key = "semapact.pr-auth-method"
        cached_method = _get_git_config(repo_path, cache_key) if repo_path else None

        if cached_method == "cli":
            try:
                return self._create_pull_request_cli(
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    description=description,
                    reviewers=reviewers,
                    repo_path=repo_path,
                )
            except Exception as e:
                LOGGER.debug(f"Cached CLI method failed (GitHub): {e}")

        if cached_method == "api":
            try:
                return self._create_pull_request_api(
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    description=description,
                    reviewers=reviewers,
                )
            except Exception as e:
                LOGGER.debug(f"Cached API method failed (GitHub): {e}")

        # 1. Native CLI
        try:
            result = self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
            )
            if repo_path:
                _set_git_config(repo_path, cache_key, "cli")
            return result
        except Exception as e:
            LOGGER.debug(f"Native CLI PR creation failed (GitHub): {e}")

        # 2. CLI with token
        try:
            result = self._create_pull_request_cli(
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                description=description,
                reviewers=reviewers,
                repo_path=repo_path,
                inject_token=True,
            )
            if repo_path:
                _set_git_config(repo_path, cache_key, "cli")
            return result
        except Exception as e:
            LOGGER.debug(f"CLI with token PR creation failed (GitHub): {e}")

        # 3. API Fallback
        result = self._create_pull_request_api(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            reviewers=reviewers,
        )
        if repo_path:
            _set_git_config(repo_path, cache_key, "api")
        return result

    def _create_pull_request_cli(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
        inject_token: bool = False,
    ) -> dict[str, Any]:
        if not repo_path:
            raise RuntimeError("repo_path is required for CLI PR creation")

        cmd = [
            "gh",
            "pr",
            "create",
            "--base",
            target_branch,
            "--head",
            source_branch,
            "--title",
            title,
            "--body",
            description,
        ]

        if reviewers:
            for reviewer in reviewers:
                cmd.extend(["--reviewer", reviewer])

        env = os.environ.copy()
        if inject_token:
            env["GH_TOKEN"] = self.config.token

        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            env=env,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to create PR in GitHub via CLI: {result.stderr}"
            )

        # Try to return standard API format if possible, otherwise wrap the URL string
        stdout_str = result.stdout.strip()
        if stdout_str.startswith("http"):
            return {"url": stdout_str, "html_url": stdout_str}

        try:
            return json.loads(stdout_str)
        except json.JSONDecodeError:
            return {"raw_output": stdout_str}

    def _create_pull_request_api(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub pull request via REST API."""
        url = (
            f"https://api.github.com/repos/{self.config.owner}/{self.config.repo}/pulls"
        )

        payload: dict[str, Any] = {
            "title": title,
            "head": source_branch,
            "base": target_branch,
            "body": description,
        }

        response = requests.post(
            url, headers=self._headers(), data=json.dumps(payload), timeout=30
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to create PR in GitHub: status={response.status_code}, body={response.text[:500]}"
            )

        pr_data = response.json()

        if reviewers:
            pr_number = pr_data.get("number")
            if pr_number:
                reviewers_url = f"{url}/{pr_number}/requested_reviewers"
                reviewers_payload = {"reviewers": reviewers}
                rev_resp = requests.post(
                    reviewers_url,
                    headers=self._headers(),
                    data=json.dumps(reviewers_payload),
                    timeout=30,
                )
                rev_resp.raise_for_status()

        return pr_data

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }


@dataclass(slots=True)
class PullRequestCreator:
    """Manage contract commits and pull requests for GitOps workflows."""

    provider: GitProvider

    def __init__(self, config: GitProviderConfig | GitProvider):
        # Support legacy init with just config
        if isinstance(config, AzureDevOpsConfig):
            self.provider = AzureDevOpsProvider(config)
        elif isinstance(config, GitHubConfig):
            self.provider = GitHubProvider(config)
        else:
            self.provider = config

    def commit_updated_contracts(
        self,
        repo_path: str,
        *,
        source_branch: str,
        commit_message: str,
        paths: list[str] | None = None,
    ) -> str:
        """Commit updated contract artifacts and return commit SHA."""
        repo = Path(repo_path).expanduser().resolve()
        self._ensure_branch(repo, source_branch)

        if paths:
            self._git(repo, ["add", *paths])
        else:
            self._git(repo, ["add", "-u"])

        status = self._git(repo, ["status", "--porcelain"], capture_output=True)
        if not status.stdout.strip():
            return self._git(
                repo, ["rev-parse", "HEAD"], capture_output=True
            ).stdout.strip()

        self._git(repo, ["commit", "-m", commit_message])
        return self._git(
            repo, ["rev-parse", "HEAD"], capture_output=True
        ).stdout.strip()

    def create_pull_request(
        self,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[str] | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Create a pull request using the configured provider."""
        return self.provider.create_pull_request(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            reviewers=reviewers,
            repo_path=repo_path,
        )

    def create_update_pr(
        self,
        *,
        repo_path: str,
        source_branch: str,
        target_branch: str,
        commit_message: str,
        title: str,
        description: str,
        paths: list[str] | None = None,
        push: bool = False,
    ) -> dict[str, Any]:
        """Commit changes and create PR in one operation."""
        self.commit_updated_contracts(
            repo_path,
            source_branch=source_branch,
            commit_message=commit_message,
            paths=paths,
        )

        if push:
            repo = Path(repo_path).expanduser().resolve()
            self._git(repo, ["push", "--set-upstream", "origin", source_branch])

        return self.create_pull_request(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            repo_path=repo_path,
        )

    @staticmethod
    def _git(
        repo: Path, args: list[str], *, capture_output: bool = False
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                text=True,
                capture_output=capture_output,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Git command timed out after 300 seconds: {' '.join(exc.cmd)}"
            ) from exc

    def _ensure_branch(self, repo: Path, source_branch: str) -> None:
        try:
            self._git(repo, ["checkout", source_branch], capture_output=True)
        except subprocess.CalledProcessError:
            self._git(repo, ["checkout", "-b", source_branch], capture_output=True)
