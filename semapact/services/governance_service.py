"""Compatibility imports for the former governance service module."""

from semapact.application.models.governance import GovernanceAnalysis, GovernanceProposal
from semapact.application.services.governance import GovernanceService

__all__ = ["GovernanceAnalysis", "GovernanceProposal", "GovernanceService"]
