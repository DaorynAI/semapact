# SemaPact Roadmap — Agentic Data Engineering Pivot

**Status:** proposed product roadmap, documentation only (2026-11-17).  
**Basis:** the user-supplied 2026-11-16 Agentic Loop gap analysis, reconciled against the current [architecture invariants](../ARCHITECTURE.md).  
**Architecture:** [Agentic Data Engineering target](agentic_engineering_architecture.md).

## Strategic decision

**Build:** the governance, verification, authorization, durable state and evidence **outer loop** for contract-grounded data engineering tasks.

**Reuse:** Data Contract CLI for standard contract operations and DQ execution; Codex/Copilot/Claude or other external coding agents for the **inner loop**; Databricks SDK / Lakeflow / DAB for execution; external Git/CI for protected merges and deployment permission. No parallel contract CLI, DQ runtime, coding harness or custom workflow/checkpoint engine.

**Initial vertical slice:** one approved ODCS contract plus quality rules, one companion pipeline artifact, one real Databricks engineering change, reproducible failure evidence and at least one agent repair iteration. The success metric is verified engineering change, not number of CLI subcommands.

## Phases and exit criteria

| Phase | Scope | Exit criteria / gate |
| --- | --- | --- |
| **0 — Manual pilot (next)** | Use current SemaPact CLI/governance/reconcile, Data Contract CLI, real Databricks runs and external coding agent. Manual step briefs, approval gates and failure/evidence capture across 2–3 representative contract-grounded ingestions. No new engine. | Approved contracts contain meaningful DQ rules; independent checks expose actual failures, agent repairs at least one; inventory evidence, tool interfaces and failure classes. |
| **1 — Minimum outer loop** | Trusted workflow loader (pinned protected ref / installed profile), schema/linter; LangGraph run/checkpoint model; run start/next/yield/submit/event/status/abort; CheckResult and system columns; budgets, no-progress and BLOCKED. CLI-first and local SQLite. | One scripted delivery step survives restart and async yield, rejects tampered profile content and stops on repeated identical failures. |
| **2 — Verification, governance & promotion** | Wrap Data Contract CLI lint/test; dual-base plan; independent quality/reconcile/doctor checks; action registry with authorize(); immutable evidence binding and managed-only classification; draft design GA, merge GC and Prod PUBLISH GR boundaries; separate contract-delivery and contract-release. | Unapproved/out-of-step actions fail closed; candidate can be staged in Test without release version/tag; Prod release requires exact Test evidence and existing formal publication governance. |
| **3 — Databricks vertical slice** | Databricks RuntimeDriver (Lakeflow/Jobs start/poll, run yield, in-pipeline quality receipts and fallback), typed framework/profile plugin v1, one isolated AgentRunner, SDP Meta reference metadata-bound framework. | A real Bronze → Silver contract change is compiled, tested, corrected and staged to Test with bound receipts through the same CLI protocol. No Test/Prod write permission in the agent worker. |
| **4 — Unattended and interchangeable** | MCP as thin core adapter; declarative trusted tools, external dispatcher/event intake and review providers, multiple AgentRunner adapters, replay evaluation harness; prove a second code-bound framework (dbt or Lakeflow-native). | Multi-day PR/compute waits resume without idle agent tokens; same outer workflow works with two agents and two framework modes; full audit/evaluation green. |
| **5 — Depth and scale** | Workflow library (schema evolution, deprecation, remediation, new data product), optional scheduled monitoring, deeper Databricks policy/lineage/cost capabilities, self-hosted server/dashboard and later additional runtimes. | Production monitoring and dashboard proven on real work; wider platform scope justified by measured demand. |

This normalizes the source draft's duplicated Phase 4 and missing Phase 3. The specific ordering between Phase 2 and 3 may be adjusted after Phase 0 evidence, but those gates and their exit criteria may not be omitted.

## Phase 0 test protocol

1. Select two to three real, small Databricks data-product tasks with source data available; include at least one schema evolution and one load-strategy / DQ failure scenario.
2. Provide the agent a human-approved ODCS contract, DQ rules and allowed companion artifacts. Pin the starting Git ref, runtime target, input data slice and toolchain versions.
3. Agent performs the inner loop using its normal coding environment. Run fast lint/plan checks before any expensive cloud operation.
4. Independent operator/CI uses existing SemaPact reconciliation and delegated DQ execution to verify completion; record concrete input/output fingerprints and a structured failure reason. No agent self-reported PASS.
5. On failure, feed the check result back to the *same step's* agent session, rerun, and record attempt count, latency, compute cost, repairs and operator interventions.
6. Document which actions require an authorization gate and where the platform's IAM or CI environment must enforce it. Delivery ends with verified Test candidate; **formal Prod release remains separate**.

**Exit artifact:** a short evaluation report with examples of passing and failing receipts, failure taxonomy, retry outcomes and the minimum needed command/step contracts for Phase 1. This report is the acceptance gate before writing a LangGraph engine.

## What to freeze / stop duplicating

| Area | Roadmap decision |
| --- | --- |
| ODCS lint, generic import/export and base diff features | Prefer Data Contract CLI; retain only SemaPact-owned lifecycle/governance semantics and proven gaps. Verify upstream feature equivalence before replacing existing code. |
| Great Expectations suite export / internal DQ runtime | Freeze feature expansion; first expose a delegated Data Contract CLI test/check adapter and consistent evidence contract. |
| Built-in LLM enrichment and provider-specific prompting | Freeze expansion; drafting is external-agent responsibility. |
| TUI, graph export and broad provider expansion | Maintenance only, unless needed for Phase 0 or a reproducible critical issue. |
| Pipeline-owned tables | Do not extend SemaPact DDL execution; delegate pipeline deployment to the framework/Databricks toolchain. |
| Source-system connectors and extraction logic | Out of scope; accept contractually defined control totals and verification receipts instead. |
| A home-grown Agent Loop, dispatcher or checkpoint engine | Do not build. Use LangGraph only for durable outer workflow; external dispatchers and coding agents remain swappable. |

Freeze does **not** mean immediate removal. Removals require a later migration plan, regression tests and a clear public-API decision.

## Non-negotiable quality gates

- **Trusted inputs:** workflows/actions/policies come from installed allowlisted profiles or pinned protected refs, never from mutable agent worktrees.
- **Permissions:** step policy checks occur before SemaPact-mediated actions; actual runtime writes stay protected by IAM/CI identity boundaries. AgentRunner has no Test/Prod write credentials.
- **Independent verification:** exit checks rerun; receipts bind exact revisions, environment, runtime run, data slice and tool version; stale evidence is invalid.
- **Finite progress:** attempt and no-progress budgets, async yield without consuming retries, deterministic BLOCKED state.
- **Separate history:** live checkpointer vs operational telemetry vs immutable Git governance ledger.
- **Release boundaries:** candidate stage ≠ ContractRelease; existing PUBLISH review and CI-owned deployment authority are preserved.
- **Minimal installation:** platform/graph/MCP dependencies stay optional and lazily loaded.

## Explicit decisions still needed

1. Runtime contract staging path and authoritative in-pipeline DQ receipt schema on Databricks.
2. Minimum pinned Data Contract CLI version supporting required lint/test/filter/JSON outputs (verify rather than assume).
3. Local LangGraph checkpoint backend and run locking, especially after resume or human edits.
4. GA design approval binding, managed-field exclusions and its relationship with existing PUBLISH approval semantics.
5. Initial SDP Meta mapping / scope relative to custom pipeline code; proof required before generalizing framework adapters.
6. Public control-totals format and whether source reconciliation is mandatory per profile.
7. When a non-contract-centric engineering task qualifies for SemaPact run identity and verification.

## Evidence-based scope control

Before adding any Phase 1+ feature, require a Phase 0 example showing why it is needed, an acceptance criterion, an existing module or upstream tool that could supply it, and a test proving the relevant trust boundary. Keep changes in the single SemaPact repository, with domain→application→interface direction as documented in the current architecture.
