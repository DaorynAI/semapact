---
name: draft-workflow
description: Defines draft-based editing and change workflow for contracts including save, analyze, and promotion steps. Use when implementing or reviewing SemaPact draft retrieval, draft persistence, draft validation, main-vs-draft analysis, and future promotion flow. Apply this skill when main contracts must stay protected while drafts persist independently and provide safe iterative editing.
---

# Draft & Change Workflow

SemaPact uses a draft-based editing model.

------------------------------------------------
FLOW

Load MAIN
  ↓
Create or Load DRAFT
  ↓
Edit Draft
  ↓
Analyze Draft vs Main
  ↓
Save Draft
  ↓
Promote (future)

------------------------------------------------
DRAFT STORAGE

Recommended:

`.semapact/drafts/{user}/{contract_id}.yaml`

------------------------------------------------
RULES

- Draft must NOT overwrite main
- Draft must persist independently
- Draft must be validated before saving

------------------------------------------------
SAVE

`save_draft`:

- validate contract
- persist draft
- do NOT modify main contract

------------------------------------------------
PROMOTION

`promote_draft`:

- compare main vs draft
- run governance checks
- classify required version bump PER CONTRACT
- require an explicit `release_tag`
- create PR (future)

------------------------------------------------
GOAL

Enable safe, iterative contract editing with real-time feedback.
