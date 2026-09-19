"""Application orchestration for production-readiness diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from semapact.application.models.readiness import (
    ReadinessCheck,
    ReadinessReport,
    ReadinessStatus,
)


class ReadinessProbe(Protocol):
    """Narrow infrastructure probe consumed by the application service."""

    key: str

    def run(self) -> tuple[ReadinessCheck, ...]: ...


class ReadinessService:
    """Aggregate provider/storage probes without owning infrastructure behavior."""

    def __init__(self, probes: Iterable[ReadinessProbe]) -> None:
        self._probes = tuple(probes)

    def check(self, *, platform: str, runtime_target: str) -> ReadinessReport:
        checks: list[ReadinessCheck] = []
        for probe in self._probes:
            try:
                checks.extend(probe.run())
            except Exception as exc:
                checks.append(
                    ReadinessCheck(
                        check_id=f"{probe.key}.probe",
                        status=ReadinessStatus.FAIL,
                        required=True,
                        summary="Readiness probe failed unexpectedly.",
                        remediation="Inspect the failing integration and retry the diagnostic.",
                        error_type=type(exc).__name__,
                    )
                )
        return ReadinessReport(
            platform=_required_text(platform, "platform"),
            runtime_target=_required_text(runtime_target, "runtime_target"),
            checks=tuple(checks),
        )


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
