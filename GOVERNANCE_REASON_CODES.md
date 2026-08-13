# Governance Reason Codes

SemaPact governance decisions expose stable machine-readable reason codes for automation, CI, APIs, audit history, and agents.

## Contract

Each item in `GovernanceDecision.reasons` contains:

- `code` — stable semantic identifier. Automation should branch on this field.
- `path` — affected contract path when one is available.
- `message` — human-readable explanation. Its wording is not an API contract.
- `severity` — canonical `ERROR`, `WARNING`, or `INFO` severity.
- `details` — optional structured evidence specific to the condition.

Do not parse `message` to determine governance behavior. New reason codes may be added over time; an existing code's meaning must not be repurposed.

The authoritative registry is `semapact.governance.GOVERNANCE_REASON_REGISTRY` and the public enum is `semapact.governance.GovernanceReasonCode`.

## Stable codes

| Code | Severity | Semantics |
| --- | --- | --- |
| `CONTRACT_ID_CHANGED` | ERROR | The governed root contract identity changed. |
| `CONTRACT_VERSION_MANUALLY_CHANGED` | ERROR | The release-managed contract version changed outside the release flow. |
| `SCHEMA_REMOVED` | WARNING | An in-scope schema was removed from an active contract. |
| `PROPERTY_REMOVED` | WARNING | An in-scope property was removed from an active contract. |
| `RELATIONSHIP_REMOVED` | WARNING | An in-scope relationship was removed from an active contract. |
| `LOGICAL_TYPE_CHANGED` | WARNING | A governed property's logical type changed. |
| `PHYSICAL_TYPE_NARROWED` | WARNING | A governed property's physical type narrowed. |
| `DECIMAL_PRECISION_REDUCED` | WARNING | Decimal precision was reduced. |
| `DECIMAL_SCALE_REDUCED` | WARNING | Decimal scale was reduced. |
| `REQUIRED_TIGHTENED` | WARNING | A property changed from optional to required. |
| `ENUM_VALUES_REMOVED` | WARNING | Allowed enum values were removed. |
| `RETIRED_CONTRACT_MODIFIED` | ERROR | A retired contract was modified. |
| `CONTRACT_RETIRED_TRANSITION` | WARNING | A contract transitioned to retired and requires review. |
| `VALIDATION_FAILED` | ERROR | Contract or identity validation failed. |
| `MERGE_CONFLICT` | WARNING | A deterministic merge conflict requires review. |
| `CHANGE_ASSESSMENT` | INFO | Version-bump classification evidence for the change set. |

## Decision semantics

Reason severity does not replace `GovernanceDecision.decision`. Consumers must use the authoritative decision and the centralized governance gate for enforcement. Codes explain the conditions that produced the decision; they do not independently redefine `ALLOW`, `REVIEW`, or `BLOCK` behavior.

For lifecycle breaking conditions, `semapact.lifecycle.policy` is the source of truth and emits the stable code together with the descriptive message. The governance evaluator forwards that code rather than inferring semantics from message text.
