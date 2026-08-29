"""Architecture regression tests for side-effect-free governance analysis."""

from __future__ import annotations

import ast
import builtins
import copy
import inspect
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from open_data_contract_standard.model import (
    OpenDataContractStandard,
    SchemaObject,
    SchemaProperty,
)

import semapact.governance.evaluator as evaluator_module
from semapact.change_context import ChangeContext
from semapact.governance.evaluator import evaluate_governance_decision
from semapact.services import GovernanceService


TEST_CONTEXT = ChangeContext(effective_date=date(2026, 1, 1))

_FORBIDDEN_LAYER_IMPORT_PREFIXES = (
    "semapact.devops",
    "semapact.exporters",
    "semapact.importers",
    "semapact.interfaces",
    "semapact.orchestrator",
    "semapact.services",
)
_FORBIDDEN_SIDE_EFFECT_IMPORT_ROOTS = {
    "git",
    "github",
    "gitlab",
    "httpx",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "urllib",
}


def _make_contract(*, include_note: bool = False) -> OpenDataContractStandard:
    properties = [
        SchemaProperty(
            name="id",
            logicalType="string",
            physicalType="varchar(255)",
            required=True,
        ),
        SchemaProperty(
            name="amount",
            logicalType="number",
            physicalType="decimal(10,2)",
            required=False,
        ),
    ]
    if include_note:
        properties.append(
            SchemaProperty(
                name="note",
                logicalType="string",
                physicalType="varchar(100)",
                required=False,
            )
        )

    return OpenDataContractStandard(
        apiVersion="v3.1.0",
        kind="DataContract",
        id="orders",
        name="orders",
        version="1.0.0",
        status="active",
        schema=[SchemaObject(name="orders", properties=properties)],
    )


def _block_external_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if analysis attempts filesystem or process side effects."""

    def forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("governance analysis attempted an external side effect")

    original_open = builtins.open

    def guarded_open(
        file: Any,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            forbidden(file, mode)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "touch", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    monkeypatch.setattr(Path, "rename", forbidden)
    monkeypatch.setattr(Path, "replace", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)


def _module_imports(module: Any) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_governance_evaluator_has_no_side_effect_layer_dependencies() -> None:
    """The authoritative evaluator must not depend on integration/mutation layers."""
    imports = _module_imports(evaluator_module)

    forbidden_layers = sorted(
        imported
        for imported in imports
        if imported.startswith(_FORBIDDEN_LAYER_IMPORT_PREFIXES)
    )
    forbidden_side_effect_modules = sorted(
        imported
        for imported in imports
        if imported.split(".", 1)[0] in _FORBIDDEN_SIDE_EFFECT_IMPORT_ROOTS
    )

    assert forbidden_layers == []
    assert forbidden_side_effect_modules == []


def test_governance_decision_evaluation_is_pure_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision construction must be repeatable without mutating inputs or the environment."""
    base = _make_contract()
    candidate = _make_contract(include_note=True)
    base_before = copy.deepcopy(base)
    candidate_before = copy.deepcopy(candidate)

    _block_external_side_effects(monkeypatch)

    first = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)
    second = evaluate_governance_decision(base, candidate, context=TEST_CONTEXT)

    assert first == second
    assert first.decision_id == second.decision_id
    assert base == base_before
    assert candidate == candidate_before


def test_governance_service_evaluate_preserves_analysis_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The application analysis entrypoint must remain side-effect free."""
    base = _make_contract()
    candidate = _make_contract(include_note=True)
    base_before = copy.deepcopy(base)
    candidate_before = copy.deepcopy(candidate)

    _block_external_side_effects(monkeypatch)

    decision = GovernanceService().evaluate(
        base,
        candidate,
        effective_date=TEST_CONTEXT.effective_date,
    )

    assert decision.context == TEST_CONTEXT
    assert base == base_before
    assert candidate == candidate_before
