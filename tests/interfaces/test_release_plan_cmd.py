from __future__ import annotations

import json
import sys

import pytest

from semapact.interfaces import cli
from semapact.interfaces.commands import release_cmd


def test_release_plan_parser_requires_explicit_revision_refs() -> None:
    args = cli._build_parser().parse_args(
        [
            "release",
            "plan",
            "--base",
            "contracts/base.yaml",
            "--candidate",
            "contracts/candidate.yaml",
            "--base-revision-ref",
            "git:base-123",
            "--candidate-revision-ref",
            "git:candidate-456",
            "--effective-date",
            "2026-09-11",
        ]
    )

    assert args.command == "release"
    assert args.release_command == "plan"
    assert args.base_revision_ref == "git:base-123"
    assert args.candidate_revision_ref == "git:candidate-456"
    assert args.authority_reference is None


def test_release_plan_parser_accepts_git_authority_reference() -> None:
    args = cli._build_parser().parse_args(
        [
            "release",
            "plan",
            "--base",
            "base.yaml",
            "--candidate",
            "candidate.yaml",
            "--base-revision-ref",
            "git:base",
            "--candidate-revision-ref",
            "git:candidate",
            "--authority-reference",
            "v2.0.0",
            "--effective-date",
            "2026-09-11",
        ]
    )

    assert args.authority_reference == "v2.0.0"


def test_main_routes_release_plan_to_release_command_adapter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "changeSet": {"change_set_id": "change-set:test"},
        "releasePlan": {"release_plan_id": "release-plan:test"},
        "versionResolution": {"version_resolution_id": "version:test"},
        "governanceDecision": {"decision_id": "decision:test"},
    }
    monkeypatch.setattr(release_cmd, "run_release_plan", lambda args: expected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "semapact",
            "release",
            "plan",
            "--base",
            "base.yaml",
            "--candidate",
            "candidate.yaml",
            "--base-revision-ref",
            "git:base",
            "--candidate-revision-ref",
            "git:candidate",
            "--effective-date",
            "2026-09-11",
        ],
    )

    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_legacy_release_helpers_are_labeled_as_compatibility_paths() -> None:
    help_text = cli._build_parser().format_help()
    release_parser = cli._build_parser()._subparsers._group_actions[0].choices["release"]
    release_help = release_parser.format_help()

    assert "release" in help_text
    assert "Compatibility helper" in release_help
    assert "Compatibility Git workflow" in release_help



def test_release_parser_exposes_assess_approve_finalize() -> None:
    parser = cli._build_parser()

    assess = parser.parse_args(
        [
            "release",
            "assess",
            "--base",
            "base.yaml",
            "--candidate",
            "candidate.yaml",
            "--base-revision-ref",
            "git:base",
            "--candidate-revision-ref",
            "git:candidate",
            "--effective-date",
            "2026-09-20",
            "--bundle-out",
            "release.bundle.json",
        ]
    )
    approve = parser.parse_args(
        [
            "release",
            "approve",
            "--bundle",
            "release.bundle.json",
            "--actor-reference",
            "github-environment:contract-release",
            "--recorded-at",
            "2026-09-20T10:00:00+10:00",
        ]
    )
    finalize = parser.parse_args(
        [
            "release",
            "finalize",
            "--bundle",
            "release.bundle.json",
            "--output-contract",
            "contract.yaml",
        ]
    )

    assert assess.release_command == "assess"
    assert assess.bundle_out == "release.bundle.json"
    assert approve.release_command == "approve"
    assert approve.repository_root == "."
    assert finalize.release_command == "finalize"
    assert finalize.output_contract == "contract.yaml"


def test_main_routes_release_assess_to_release_command_adapter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {"bundle_digest": "sha256:test"}
    monkeypatch.setattr(release_cmd, "run_release_assess", lambda args: expected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "semapact",
            "release",
            "assess",
            "--base",
            "base.yaml",
            "--candidate",
            "candidate.yaml",
            "--base-revision-ref",
            "git:base",
            "--candidate-revision-ref",
            "git:candidate",
            "--effective-date",
            "2026-09-20",
        ],
    )

    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == expected
