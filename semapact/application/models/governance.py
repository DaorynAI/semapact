"""Application result models for governance use cases."""

from __future__ import annotations

from dataclasses import dataclass

from semapact.change_context import ChangeContext
from semapact.contractops import ChangeSet
from semapact.governance.models import GovernanceDecision
from semapact.lifecycle.merge_engine import MergeResult


@dataclass(frozen=True)
class GovernanceAnalysis:
    """One merge-and-governance analysis using a single resolved context."""

    context: ChangeContext
    merge_result: MergeResult
    decision: GovernanceDecision


@dataclass(frozen=True)
class GovernanceProposal:
    """One evaluated proposal represented by a ChangeSet and its decision."""

    change_set: ChangeSet
    decision: GovernanceDecision
