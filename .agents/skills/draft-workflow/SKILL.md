---
name: draft-workflow
description: Defines current draft-based editing and change workflow for governed contracts. Use when implementing or reviewing draft retrieval, persistence, validation, and main-vs-draft analysis.
---

# Draft & Change Workflow

SemaPact uses a draft-based editing model so presentation paths do not overwrite canonical governed state.

------------------------------------------------
CURRENT FLOW

Load MAIN
  ↓
Create or Load DRAFT
  ↓
Edit Draft
  ↓
Validate / Analyze Draft vs Main
  ↓
Save Draft

------------------------------------------------
DRAFT STORAGE

Current draft storage convention:

`.semapact/drafts/{user}/{contract_id}.yaml`

------------------------------------------------
RULES

- Draft must NOT overwrite main.
- Draft must persist independently from canonical main state.
- Draft must be validated before saving.
- UI/API/CLI code must not implement lifecycle or merge policy directly.
- Any path that attempts to move draft state into governed main state must use the canonical governance, authorization, and GitOps boundaries rather than writing main directly.

------------------------------------------------
SAVE

`save_draft`:

- validate the candidate draft;
- persist draft state only;
- do NOT modify the main contract;
- preserve non-editable governed/technical fields according to the application/domain rules.

------------------------------------------------
ANALYSIS

Main-vs-draft analysis:

- compares the exact governed main revision with the draft candidate;
- delegates lifecycle/breaking/deprecation policy to the canonical governance layer;
- returns analysis artifacts without mutating main or draft implicitly.

------------------------------------------------
GOAL

Enable safe iterative editing while keeping canonical governed state protected from presentation-layer writes.
