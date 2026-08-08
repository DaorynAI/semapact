import argparse
import os
import yaml
from pathlib import Path

def run_init(args: argparse.Namespace) -> None:
    config_path = Path.cwd() / ".semapact.yaml"
    if not config_path.exists():
        default_config = {
            "azure": {
                "auth_method": "cli",
                "scope": "https://storage.azure.com/.default"
            },
            "git": {
                "provider": "azure",
                "organization": "your-organization",
                "project": "your-project",
                "repository_id": "your-repo-id",
            },
            "databricks": {
                "profile": "",
                "workspace_url": "",
                "token": "",
                "sql_http_path": ""
            },
            "core": {
                "enforce_lifecycle": True
            },
            "llm": {
                "model_name": "gpt-4-turbo",
                "api_key": "",
                "base_url": ""
            }
        }
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(default_config, f, default_flow_style=False, sort_keys=False)
        
        from semapact.core.config import config_manager
        config_manager._load_configs()
        
        print(f"✅ Successfully generated default configuration at {config_path}")
        
        gitignore_path = Path(".gitignore")
        gitignore_entry = ".semapact.yaml"
        if gitignore_path.exists():
            content = gitignore_path.read_text(encoding="utf-8")
            if gitignore_entry not in content:
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{gitignore_entry}\n")
                print(f"📝 Appended {gitignore_entry} to .gitignore")
        else:
            gitignore_path.write_text(f"{gitignore_entry}\n", encoding="utf-8")
            print(f"📝 Created .gitignore with {gitignore_entry}")

        print("   💡 Default git.provider is set to 'azure'. Edit this file to use 'github' or 'gitlab' instead.")
        if not getattr(args, "scaffold", False):
            print("   💡 Run `semapact init --scaffold` to bootstrap a repository with CI/CD pipelines based on this configuration.")
    else:
        print(f"✅ Configuration file already exists at {config_path}")

    if getattr(args, "scaffold", False):
        from semapact.core.config import config_manager
        provider = config_manager.get("git.provider", "SEMAPACT_GIT_PROVIDER", "azure").lower()
        print(f"🚀 Bootstrapping SemaPact repository (using git.provider: '{provider}')...")

        # Base directories
        dirs = ["contracts"]
        if provider == "github":
            dirs.append(".github/workflows")
        elif provider == "gitlab":
            dirs.append(".gitlab/ci")
            
        for d in dirs:
            os.makedirs(d, exist_ok=True)
            print(f"📁 Created directory: {d}")

        if provider == "github":
            github_action = """name: Contract Check
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Base Branch
        uses: actions/checkout@v4
        with:
          ref: ${{ github.base_ref }}
          path: contracts-main
      - name: Checkout PR Branch
        uses: actions/checkout@v4
        with:
          path: contracts-feature
      - name: Install uv and deps
        run: pip install uv && uv venv && uv pip install semapact
      - name: Contract Check
        run: semapact release classify-repo --base-root contracts-main/contracts --candidate-root contracts-feature/contracts
"""
            gh_action_path = ".github/workflows/contract-check.yaml"
            if not os.path.exists(gh_action_path):
                with open(gh_action_path, "w") as f:
                    f.write(github_action)
                print(f"📄 Created GitHub Actions workflow: {gh_action_path}")
            else:
                print(f"⏭️ Skipped existing GitHub Actions workflow: {gh_action_path}")

        elif provider == "gitlab":
            gitlab_ci = """stages:
  - validate

contract_check:
  stage: validate
  image: python:3.11-slim
  script:
    - git clone --depth 1 --branch $CI_MERGE_REQUEST_TARGET_BRANCH_NAME $CI_REPOSITORY_URL contracts-main
    - git clone --depth 1 --branch $CI_COMMIT_REF_NAME $CI_REPOSITORY_URL contracts-feature
    - pip install uv
    - uv venv && uv pip install semapact
    - semapact release classify-repo --base-root contracts-main/contracts --candidate-root contracts-feature/contracts
"""
            gitlab_ci_path = ".gitlab/ci/contract-check.yml"
            if not os.path.exists(gitlab_ci_path):
                with open(gitlab_ci_path, "w") as f:
                    f.write(gitlab_ci)
                print(f"📝 Created {gitlab_ci_path}")
            else:
                print(f"⏭️ Skipped existing GitLab CI workflow: {gitlab_ci_path}")
            
        elif provider == "azure":
            protocol = config_manager.get("git.protocol", "SEMAPACT_GIT_PROTOCOL", "https").lower()
            if protocol == "ssh":
                checkout_script = """  - script: |
      git clone --depth 1 --branch main git@ssh.dev.azure.com:v3/$(System.TeamFoundationCollectionUri)/$(System.TeamProject)/$(Build.Repository.Name) $(Agent.BuildDirectory)/contracts-main
    displayName: Checkout Base Branch (SSH)"""
            else:
                checkout_script = """  - script: |
      git -c http.extraHeader="AUTHORIZATION: bearer $SYSTEM_ACCESSTOKEN" clone --depth 1 --branch main https://dev.azure.com/$(System.TeamFoundationCollectionUri)/$(System.TeamProject)/_git/$(Build.Repository.Name) $(Agent.BuildDirectory)/contracts-main
    displayName: Checkout Base Branch (HTTPS)
    env:
      SYSTEM_ACCESSTOKEN: $(System.AccessToken)"""

            azure_pipeline = f"""trigger: none

pr:
  branches:
    include:
      - main

pool:
  vmImage: ubuntu-latest

steps:
  - checkout: self
    path: contracts-feature

{checkout_script}

  - script: |
      python -m pip install uv
      uv venv && uv pip install semapact
    displayName: Install dependencies

  - script: |
      semapact release classify-repo \\
        --base-root $(Agent.BuildDirectory)/contracts-main/contracts \\
        --candidate-root $(Agent.BuildDirectory)/contracts-feature/contracts
    displayName: Classify per-contract required bumps
"""
            azure_path = "azure-pipelines.yml"
            if not os.path.exists(azure_path):
                with open(azure_path, "w") as f:
                    f.write(azure_pipeline)
                print(f"📝 Created {azure_path}")
            else:
                print(f"⏭️ Skipped existing Azure Pipeline: {azure_path}")

    # Try to initialize a default contract using datacontract-cli
    try:
        print("📝 Generating sample contract via datacontract-cli...")
        # Just write a basic one manually to avoid click testing issues
        sample_yaml = """
apiVersion: v3.1.0
kind: DataContract
id: sample-contract
name: Sample Contract
version: 1.0.0
status: draft
schema:
  - id: sample
    name: sample
    physicalType: table
    properties:
      - id: col1
        name: col1
        physicalType: string
"""
        sample_path = "contracts/sample.yaml"
        if not os.path.exists(sample_path):
            os.makedirs("contracts", exist_ok=True)
            with open(sample_path, "w") as f:
                f.write(sample_yaml.lstrip())
            print(f"📄 Created sample contract: {sample_path}")
        else:
            print(f"⏭️ Skipped existing sample contract: {sample_path}")
    except Exception:
        import logging

        logging.getLogger("semapact").debug(
            "Failed to generate sample contract via datacontract-cli", exc_info=True
        )

    print("✅ Setup complete! You can now use GitOps for your data contracts.")
