"""Compatibility import for lifecycle-owned governed change classification."""

from semapact.lifecycle.change_classification import (
    ContractChangeAssessment,
    classify_contract_change,
)

__all__ = ["ContractChangeAssessment", "classify_contract_change"]
