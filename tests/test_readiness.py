from __future__ import annotations

from semapact.application.models.readiness import (
    ReadinessCheck,
    ReadinessStatus,
)
from semapact.application.services.readiness import ReadinessService
from semapact.platforms.git.readiness import GitWorkingTreeReadinessProbe


class _Probe:
    key = "test"

    def __init__(self, *checks: ReadinessCheck) -> None:
        self._checks = checks

    def run(self) -> tuple[ReadinessCheck, ...]:
        return self._checks


def test_optional_warning_does_not_block_readiness() -> None:
    report = ReadinessService(
        (
            _Probe(
                ReadinessCheck(
                    check_id="test.required",
                    status=ReadinessStatus.PASS,
                    required=True,
                    summary="Required prerequisite passed.",
                ),
                ReadinessCheck(
                    check_id="test.optional",
                    status=ReadinessStatus.WARN,
                    required=False,
                    summary="Optional integration is unavailable.",
                ),
            ),
        )
    ).check(platform="databricks", runtime_target="main.sales")

    assert report.ready is True


def test_required_failure_blocks_readiness() -> None:
    report = ReadinessService(
        (
            _Probe(
                ReadinessCheck(
                    check_id="test.required",
                    status=ReadinessStatus.FAIL,
                    required=True,
                    summary="Required prerequisite failed.",
                )
            ),
        )
    ).check(platform="databricks", runtime_target="main.sales")

    assert report.ready is False


def test_unexpected_probe_failure_is_secret_safe() -> None:
    class _ExplodingProbe:
        key = "explode"

        def run(self) -> tuple[ReadinessCheck, ...]:
            raise RuntimeError("credential=secret-token")

    report = ReadinessService((_ExplodingProbe(),)).check(
        platform="databricks",
        runtime_target="main.sales",
    )

    check = report.checks[0]
    assert check.status is ReadinessStatus.FAIL
    assert check.error_type == "RuntimeError"
    assert "secret-token" not in check.summary
    assert "secret-token" not in (check.remediation or "")


def test_git_history_probe_is_read_only_and_missing_git_is_optional(tmp_path) -> None:
    probe = GitWorkingTreeReadinessProbe(tmp_path)

    report = ReadinessService((probe,)).check(
        platform="databricks",
        runtime_target="main.sales",
    )
    checks = {check.check_id: check for check in report.checks}

    assert checks["history.repository_root"].status is ReadinessStatus.PASS
    assert checks["history.storage"].status is ReadinessStatus.PASS
    assert checks["git.worktree"].status is ReadinessStatus.WARN
    assert checks["git.worktree"].required is False
    assert report.ready is True
    assert not (tmp_path / ".semapact").exists()
