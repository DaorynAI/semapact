import argparse
import os
import pytest
from semapact.interfaces.commands.utils import _get_repo_path
from unittest.mock import patch

def test_get_repo_path_from_args():
    args = argparse.Namespace(repo_path="/path/from/args")
    assert _get_repo_path(args) == "/path/from/args"

@patch.dict(os.environ, {"GITHUB_WORKSPACE": "/path/from/gh"}, clear=True)
def test_get_repo_path_from_github_workspace():
    args = argparse.Namespace(repo_path=None)
    assert _get_repo_path(args) == "/path/from/gh"

@patch.dict(os.environ, {"BUILD_SOURCESDIRECTORY": "/path/from/az"}, clear=True)
def test_get_repo_path_from_azure_workspace():
    args = argparse.Namespace(repo_path=None)
    assert _get_repo_path(args) == "/path/from/az"

@patch.dict(os.environ, {}, clear=True)
def test_get_repo_path_raises_error():
    args = argparse.Namespace(repo_path=None)
    with pytest.raises(ValueError, match="Could not determine repository path"):
        _get_repo_path(args)
