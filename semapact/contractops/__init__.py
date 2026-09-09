"""M2 ContractOps proposal domain."""

from semapact.contractops.changeset import (
    build_change_set,
    build_change_set_from_decision,
)
from semapact.contractops.models import ChangeSet

__all__ = [
    "ChangeSet",
    "build_change_set",
    "build_change_set_from_decision",
]
