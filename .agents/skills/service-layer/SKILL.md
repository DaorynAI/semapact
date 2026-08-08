---
name: service-layer
description: Defines the SemaPact backend service layer between the UI and system logic. Use when implementing or reviewing `semapact/interfaces/streamlit/services/` for contract loading, draft management, validation, permissions, and governance integration. Apply this skill when services must remain UI-independent, reuse `semapact.core`, `semapact.lifecycle`, and `semapact.utils`, and expose thin APIs such as `list_contracts`, `get_contract`, `get_draft`, `save_draft`, and `analyze`.
---

# Service Layer

This is the ONLY boundary between UI and system logic.

------------------------------------------------
RESPONSIBILITIES

- load main contracts
- manage drafts
- enforce permissions
- validate contracts
- run governance analysis

------------------------------------------------
STRICT RULES

- UI must NOT access YAML directly
- UI must NOT implement business logic
- service must NOT depend on UI modules
- Service methods MUST strictly accept and return the `OpenDataContractStandard` Pydantic model or formal Data Classes
- Do NOT fallback to returning or manipulating raw `dict[str, Any]` to accommodate the UI (the ODCS model is the single source of truth)

------------------------------------------------
ALLOWED DEPENDENCIES

- `semapact.core`
- `semapact.lifecycle`
- `semapact.utils`

------------------------------------------------
APIS

Main:
- `list_contracts(user)`
- `get_contract(contract_id)`

Draft:
- `get_draft(contract_id, user)`
- `save_draft(contract, user)`

Governance:
- `analyze(main, draft)`

Future:
- `promote_draft(contract_id, user)`

------------------------------------------------
IMPLEMENTATION GUIDANCE

Keep services thin.

Preferred flow:

1. resolve paths and storage configuration
2. read or write YAML via `semapact.utils.yaml_utils`
3. validate via shared core validation
4. enforce permissions before mutation
5. delegate governance analysis to lifecycle wrappers
6. return plain service results

------------------------------------------------
FORBIDDEN

- overwriting main contract directly from the UI path
- duplicating validation logic
- bypassing permission checks
- putting merge or lifecycle policy logic into non-governance services
- importing Streamlit or using `st.session_state`

------------------------------------------------
REVIEW CHECKLIST

When reviewing a SemaPact service module, check:

1. Does it keep UI and YAML access separated?
2. Does it reuse `yaml_utils` instead of reimplementing file IO?
3. Does it call shared validation instead of inline schema checks?
4. Does it enforce permissions consistently?
5. Does it keep governance logic delegated to the lifecycle layer?
6. Does it avoid overwriting the main contract in draft flows?

------------------------------------------------
Read these first-class Agent Skills when needed:

- [semapact-system](../../semapact-system/SKILL.md) for system architecture rules
- [lifecycle-policy](../../lifecycle-policy/SKILL.md) for contract lifecycle and deprecation logic
- [streamlit-ui](../../streamlit-ui/SKILL.md) for UI UX guidelines
