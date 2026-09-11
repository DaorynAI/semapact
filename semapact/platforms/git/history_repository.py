"""Immutable governance-history persistence in a Git working tree.

The adapter owns file layout only. It does not invoke Git, create commits, or create
pull requests; normal GitOps tooling can version the deterministic files it writes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

from semapact.contractops import ChangeSet
from semapact.governance import GovernanceDecision
from semapact.history import (
    HistoryConflictError,
    HistoryCorruptionError,
    HistoryNotFoundError,
)
from semapact.utils.deterministic import canonical_compact_json


T = TypeVar("T", bound=BaseModel)
_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class GitWorkingTreeHistoryRepository:
    """Persist canonical history artifacts under a SemaPact-owned working-tree path."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        state_directory: str | Path = ".semapact/history",
    ) -> None:
        self._history_root = Path(repository_root) / Path(state_directory)

    def put_decision(self, decision: GovernanceDecision) -> None:
        self._put(
            kind="decisions",
            artifact_id=decision.decision_id,
            artifact=decision,
            model_type=GovernanceDecision,
            id_attribute="decision_id",
        )

    def get_decision(self, decision_id: str) -> GovernanceDecision:
        return self._get(
            kind="decisions",
            artifact_id=decision_id,
            model_type=GovernanceDecision,
            id_attribute="decision_id",
        )

    def list_decisions(self, contract_id: str) -> tuple[GovernanceDecision, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        records = self._list(
            kind="decisions",
            model_type=GovernanceDecision,
            id_attribute="decision_id",
        )
        return tuple(record for record in records if record.contract_id == contract_id)

    def put_change_set(self, change_set: ChangeSet) -> None:
        self._put(
            kind="change_sets",
            artifact_id=change_set.change_set_id,
            artifact=change_set,
            model_type=ChangeSet,
            id_attribute="change_set_id",
        )

    def get_change_set(self, change_set_id: str) -> ChangeSet:
        return self._get(
            kind="change_sets",
            artifact_id=change_set_id,
            model_type=ChangeSet,
            id_attribute="change_set_id",
        )

    def list_change_sets(self, contract_id: str) -> tuple[ChangeSet, ...]:
        contract_id = _required_text(contract_id, "contract_id")
        records = self._list(
            kind="change_sets",
            model_type=ChangeSet,
            id_attribute="change_set_id",
        )
        return tuple(record for record in records if record.contract_id == contract_id)

    def _put(
        self,
        *,
        kind: str,
        artifact_id: str,
        artifact: T,
        model_type: type[T],
        id_attribute: str,
    ) -> None:
        artifact_id = _safe_artifact_id(artifact_id)
        canonical = self._validated_canonical_json(
            artifact,
            model_type=model_type,
            expected_id=artifact_id,
            id_attribute=id_attribute,
        )
        path = self._artifact_path(kind, artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            self._require_idempotent_existing(
                path,
                canonical=canonical,
                model_type=model_type,
                expected_id=artifact_id,
                id_attribute=id_attribute,
            )
            return

        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical)
        except FileExistsError:
            # Another writer won the create race. Treat identical content as the
            # same idempotent write and fail closed on any conflict.
            self._require_idempotent_existing(
                path,
                canonical=canonical,
                model_type=model_type,
                expected_id=artifact_id,
                id_attribute=id_attribute,
            )

    def _get(
        self,
        *,
        kind: str,
        artifact_id: str,
        model_type: type[T],
        id_attribute: str,
    ) -> T:
        artifact_id = _safe_artifact_id(artifact_id)
        path = self._artifact_path(kind, artifact_id)
        if not path.is_file():
            raise HistoryNotFoundError(
                f"{model_type.__name__} {artifact_id!r} was not found"
            )
        return self._read_validated(
            path,
            model_type=model_type,
            expected_id=artifact_id,
            id_attribute=id_attribute,
        )

    def _list(
        self,
        *,
        kind: str,
        model_type: type[T],
        id_attribute: str,
    ) -> tuple[T, ...]:
        directory = self._history_root / kind
        if not directory.is_dir():
            return ()

        records: list[T] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
            artifact_id = _safe_artifact_id(path.stem)
            records.append(
                self._read_validated(
                    path,
                    model_type=model_type,
                    expected_id=artifact_id,
                    id_attribute=id_attribute,
                )
            )
        return tuple(records)

    def _require_idempotent_existing(
        self,
        path: Path,
        *,
        canonical: str,
        model_type: type[T],
        expected_id: str,
        id_attribute: str,
    ) -> None:
        existing = self._read_validated(
            path,
            model_type=model_type,
            expected_id=expected_id,
            id_attribute=id_attribute,
        )
        existing_canonical = canonical_compact_json(existing.model_dump(mode="json"))
        if existing_canonical != canonical:
            raise HistoryConflictError(
                f"{model_type.__name__} {expected_id!r} already exists with different content"
            )

    def _read_validated(
        self,
        path: Path,
        *,
        model_type: type[T],
        expected_id: str,
        id_attribute: str,
    ) -> T:
        try:
            raw = path.read_text(encoding="utf-8")
            artifact = model_type.model_validate_json(raw)
        except (OSError, PydanticValidationError, ValueError) as exc:
            raise HistoryCorruptionError(
                f"Persisted {model_type.__name__} {expected_id!r} is invalid"
            ) from exc

        actual_id = getattr(artifact, id_attribute)
        if actual_id != expected_id:
            raise HistoryCorruptionError(
                f"Persisted {model_type.__name__} identity does not match its file identity"
            )
        return artifact

    def _validated_canonical_json(
        self,
        artifact: T,
        *,
        model_type: type[T],
        expected_id: str,
        id_attribute: str,
    ) -> str:
        if not isinstance(artifact, model_type):
            raise TypeError(
                f"artifact must be {model_type.__name__}, got {type(artifact).__name__}"
            )
        try:
            canonical = canonical_compact_json(artifact.model_dump(mode="json"))
            validated = model_type.model_validate_json(canonical)
        except (PydanticValidationError, ValueError) as exc:
            raise HistoryCorruptionError(
                f"Supplied {model_type.__name__} {expected_id!r} is invalid"
            ) from exc
        if getattr(validated, id_attribute) != expected_id:
            raise HistoryCorruptionError(
                f"Supplied {model_type.__name__} identity does not match its artifact ID"
            )
        return canonical

    def _artifact_path(self, kind: str, artifact_id: str) -> Path:
        return self._history_root / kind / f"{artifact_id}.json"


def _safe_artifact_id(value: str) -> str:
    cleaned = _required_text(value, "artifact_id")
    if not _SAFE_ARTIFACT_ID.fullmatch(cleaned):
        raise ValueError("artifact_id contains characters unsafe for history file names")
    return cleaned


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be str")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned
