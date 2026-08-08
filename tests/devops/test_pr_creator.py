from unittest.mock import patch, MagicMock
from semapact.devops.pr_creator import _get_git_config, _set_git_config, GitHubConfig, GitHubProvider, AzureDevOpsConfig, AzureDevOpsProvider
import os

@patch("semapact.devops.pr_creator.subprocess.run")
def test_get_git_config_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="cli\n")
    result = _get_git_config("/mock/repo", "semapact.pr-auth-method")

    mock_run.assert_called_once_with(
        ["git", "-C", "/mock/repo", "config", "--local", "--get", "semapact.pr-auth-method"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result == "cli"

@patch("semapact.devops.pr_creator.subprocess.run")
def test_get_git_config_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    result = _get_git_config("/mock/repo", "semapact.pr-auth-method")
    assert result is None

@patch("semapact.devops.pr_creator.subprocess.run")
def test_get_git_config_exception(mock_run):
    mock_run.side_effect = Exception("git error")
    result = _get_git_config("/mock/repo", "semapact.pr-auth-method")
    assert result is None

@patch("semapact.devops.pr_creator.subprocess.run")
def test_set_git_config_success(mock_run):
    _set_git_config("/mock/repo", "semapact.pr-auth-method", "api")
    mock_run.assert_called_once_with(
        ["git", "-C", "/mock/repo", "config", "--local", "semapact.pr-auth-method", "api"],
        check=True,
    )

@patch("semapact.devops.pr_creator.subprocess.run")
def test_set_git_config_exception_swallowed(mock_run):
    mock_run.side_effect = Exception("git error")
    # Should not raise
    _set_git_config("/mock/repo", "semapact.pr-auth-method", "api")

@patch.dict(os.environ, {"SEMAPACT_PR_METHOD": "api"}, clear=True)
@patch.object(GitHubProvider, "_create_pull_request_api")
@patch.object(GitHubProvider, "_create_pull_request_cli")
def test_github_provider_override_api(mock_cli, mock_api):
    config = GitHubConfig(owner="owner", repo="repo", token="token")
    provider = GitHubProvider(config)
    mock_api.return_value = {"id": 1}

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"id": 1}
    mock_api.assert_called_once()
    mock_cli.assert_not_called()

@patch.dict(os.environ, {"SEMAPACT_PR_METHOD": "cli"}, clear=True)
@patch.object(GitHubProvider, "_create_pull_request_api")
@patch.object(GitHubProvider, "_create_pull_request_cli")
def test_github_provider_override_cli(mock_cli, mock_api):
    config = GitHubConfig(owner="owner", repo="repo", token="token")
    provider = GitHubProvider(config)
    mock_cli.return_value = {"url": "http://github.com"}

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"url": "http://github.com"}
    mock_cli.assert_called_once()
    mock_api.assert_not_called()

@patch.dict(os.environ, {}, clear=True)
@patch("semapact.devops.pr_creator._get_git_config")
@patch.object(GitHubProvider, "_create_pull_request_api")
@patch.object(GitHubProvider, "_create_pull_request_cli")
def test_github_provider_cached_cli(mock_cli, mock_api, mock_get_cache):
    mock_get_cache.return_value = "cli"
    config = GitHubConfig(owner="owner", repo="repo", token="token")
    provider = GitHubProvider(config)
    mock_cli.return_value = {"url": "http://github.com"}

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"url": "http://github.com"}
    mock_cli.assert_called_once()
    mock_api.assert_not_called()

@patch.dict(os.environ, {}, clear=True)
@patch("semapact.devops.pr_creator._get_git_config")
@patch.object(GitHubProvider, "_create_pull_request_api")
@patch.object(GitHubProvider, "_create_pull_request_cli")
def test_github_provider_cached_api(mock_cli, mock_api, mock_get_cache):
    mock_get_cache.return_value = "api"
    config = GitHubConfig(owner="owner", repo="repo", token="token")
    provider = GitHubProvider(config)
    mock_api.return_value = {"id": 1}

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"id": 1}
    mock_api.assert_called_once()
    mock_cli.assert_not_called()

@patch.dict(os.environ, {}, clear=True)
@patch("semapact.devops.pr_creator._get_git_config")
@patch("semapact.devops.pr_creator._set_git_config")
@patch.object(GitHubProvider, "_create_pull_request_api")
@patch.object(GitHubProvider, "_create_pull_request_cli")
def test_github_provider_fallback_chain(mock_cli, mock_api, mock_set_cache, mock_get_cache):
    mock_get_cache.return_value = None
    config = GitHubConfig(owner="owner", repo="repo", token="token")
    provider = GitHubProvider(config)

    # Make CLI fail, API succeed
    mock_cli.side_effect = Exception("CLI failed")
    mock_api.return_value = {"id": 1}

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"id": 1}
    # CLI was called twice (without and with token inject)
    assert mock_cli.call_count == 2
    mock_api.assert_called_once()

    # Assert cache was set to api
    mock_set_cache.assert_called_once_with("/mock/repo", "semapact.pr-auth-method", "api")


@patch.dict(os.environ, {}, clear=True)
@patch("semapact.devops.pr_creator._get_git_config")
@patch("semapact.devops.pr_creator._set_git_config")
@patch.object(AzureDevOpsProvider, "_create_pull_request_api")
@patch.object(AzureDevOpsProvider, "_create_pull_request_cli")
def test_azure_devops_provider_fallback_chain(mock_cli, mock_api, mock_set_cache, mock_get_cache):
    mock_get_cache.return_value = None
    config = AzureDevOpsConfig(organization="org", project="proj", repository_id="repo", pat_token="token")
    provider = AzureDevOpsProvider(config)

    # Make CLI without token fail, CLI with token succeed
    mock_cli.side_effect = [Exception("CLI failed"), {"id": 1}]

    result = provider.create_pull_request(
        source_branch="feat",
        target_branch="main",
        title="title",
        description="desc",
        repo_path="/mock/repo",
    )
    assert result == {"id": 1}
    # CLI was called twice
    assert mock_cli.call_count == 2
    # API never called
    mock_api.assert_not_called()

    # Assert cache was set to cli
    mock_set_cache.assert_called_once_with("/mock/repo", "semapact.pr-auth-method", "cli")
