# Agentic Data Engineering — Target Architecture

**Status:** proposed target architecture, not a claim about currently shipped capabilities.  
**Design input:** the 2026-11-16 “semapact as an Agentic Loop Engine — Gap Analysis” and companion five-plane architecture diagram.  
**Canonical current-state invariants:** [../ARCHITECTURE.md](../ARCHITECTURE.md).

## Product boundary and non-goals

SemaPact's target is a **governed Agentic Data Engineering loop engine**: it governs the development cycle of a contract-grounded engineering change, independently verifies step completion, controls which operations may be attempted, and preserves review and execution evidence.

It is **not** a competing Data Contract CLI, a coding-agent harness, a pipeline runtime, a data catalog, or a general agent scheduler. Initially, the loop remains **contract-centric**: an ODCS contract defines governed intent, and an optional set of companion artifacts (pipeline configuration, job definitions, code) is bound to the same change. Other engineering tasks may be added by trusted workflow profiles only after this vertical slice is proven.

| Owner | Responsibility |
| --- | --- |
| **SemaPact outer loop** | Trusted workflow definition, step order, conditional routing, budgets, waits, evidence, deterministic exit checks, governance and authorization policy |
| **External coding agent inner loop** | Investigate, plan, edit artifacts, run fast self-checks, repair failures; does not certify its own step exit |
| **Data Contract CLI / ODCS** | Contract syntax, schema and DQ testing, standard imports/exports and change-analysis primitives |
| **Runtime and pipeline toolchain** | Execute pipelines and tests through Databricks SDK, Lakeflow, DAB, or another platform; return observed evidence |
| **Trusted organization profiles** | Extend steps, checks, actions, managed fields, runtime/framework drivers and policies without modifying the core |
| **Git/CI/review platform** | Protected source refs, human review, branch policies, credentials and protected deployment environments |

The outer loop is deterministic and independent of a specific LLM provider; the agent may choose its own internal reasoning/repair sequence but cannot advance the graph or assert PASS unilaterally.

## Five planes and trust boundaries

1. **Git Review & Event Dispatch.** Protected main is the trust root for workflow/policy definitions. GitHub and Azure DevOps are review-provider options. External event intake wakes runs but does not itself approve them. Dispatch is manual CLI initially, externally hosted later; no idle LLM calls.
2. **Untrusted Agent Execution.** An external AgentRunner operates in an isolated worktree with time/run budget, step-scoped capability, no Test/Prod write credentials, and bounded permissions. Session continuation within a repair step is allowed; a new step receives a fresh brief.
3. **SemaPact Control Plane.** One canonical workflow/check/action protocol exposed through CLI first, later MCP. A trusted loader resolves workflows from allowlisted installed packages or a pinned protected Git revision, never from the mutable feature worktree. GovernanceDecision, immutable change/release/deployment artifacts, exit checks and state transitions have one owner each.
4. **Three Separate Stores.** (a) LangGraph checkpoint for live workflow state and interrupts; (b) configured operational history (SQLite or Delta) for append-only step results, receipts and telemetry; (c) Git governance ledger for immutable approvals and formal release facts at deliberate commit boundaries. Operational history must not become a replay source for the live graph; checkpoints must not become the audit ledger.
5. **Runtime & Profiles.** RuntimeDriver abstracts *where* validation/deployment occurs; PipelineFrameworkDriver abstracts *how* pipeline artifacts are generated and run. Databricks is the first runtime. SDP Meta is a proposed reference framework, not a hard dependency. ODCS servers remain contract source/consumer metadata, not runtime-driver selection.

~~~mermaid
flowchart TB
  Git["Protected Git and review events"] --> Outer["SemaPact: trusted outer loop"]
  Outer --> Brief["Step brief / permitted checks and actions"]
  Brief --> Agent["External coding agent: inner edit/test/repair loop"]
  Agent --> Submit["Submit result or yield on asynchronous work"]
  Submit --> Verify["SemaPact: independent exit checks"]
  Verify -->|"failed + budget remains"| Brief
  Verify -->|"passed"| Gate["Governance / review / action gates"]
  Gate -->|"next step"| Outer
  Gate -->|"blocked / needs human"| Wait["Checkpointed wait"]
  Wait -->|"review / runtime event"| Outer
  Verify --> Evidence["Operational history + evidence"]
  Outer --> Checkpoint["LangGraph checkpointer"]
  Gate --> Ledger["Git approval / release ledger"]
  Agent -.-> Tools["Data Contract CLI / Databricks / Framework plugins"]
  Verify -.-> Tools
~~~

## One step protocol

- **run start:** pin contract identity, base and candidate Git revisions, current production release baseline, trusted workflow/profile ref, external ticket, companion artifact fingerprints and runtime/framework selection. Enforce one active run per contract and resource-level serialization where needed.
- **run next:** return a structured brief (goal, context, explicit allowed operations, tests, evidence requirements) to the external agent.
- **run yield:** suspend on an asynchronous event (e.g. Lakeflow update) without holding an agent subprocess open, running premature exit checks, or consuming a failed attempt.
- **run submit:** independently rerun exit checks, record typed CheckResults (check, pass, failure_class, fingerprint, evidence), verify evidence binding and choose a deterministic edge. The agent's narrative is never proof of completion.
- **run event/status/abort:** resume from external events, inspect status, or compensate/clean up where supported. Bounded retries, no-progress fingerprints, wall-time/round budgets and BLOCKED are required.
- **Resume integrity:** re-evaluate changed Git refs/PR revisions after human intervention; invalidate stale checks and approvals if governed content changed outside the declared managed-fields projection.

Checks must be bound to the precise contract revision, code/config SHA, environment, run/load IDs, dependency version and relevant data slice. No reuse of a PASS result for a changed candidate or a different runtime execution. Failed-row samples and secrets must be redacted before persistence or PR reporting.

## Delivery and formal release are distinct workflows

**Proposed contract-delivery** (candidate only):

1. Draft change and companion artifacts; run lint, dual-base plan (against main and latest formal Prod release), static checks and impact assessment.
2. **GA:** human design sign-off on the draft change, captured as bound approval evidence where required; managed-only generated IDs may be excluded from its *content* digest by explicit policy.
3. Agent builds / tests in **dev**, using scoped action capabilities. Independent quality, reconciliation, pipeline run receipts and optional source-control-totals checks decide step exit.
4. **GC:** ordinary protected Git PR merge review. Merge to main triggers CI-owned candidate staging and verification in **tst**; record a Test verification receipt and end as **staged**. This does not calculate or publish a contract release version.

**Proposed contract-release** (formal publication):

1. Assess main against the latest formal Prod ContractRelease; require valid Test-staged evidence for the exact candidate.
2. **GR:** formal PUBLISH review when governance requires it; finalize an immutable ContractRelease using existing ReleaseSnapshot/ReleaseBundle and version-authority rules.
3. Protected CD deploys to **prd** using exact DeploymentBundle, fresh observation and preview, then records reconciliation evidence and any canonical release provenance tags.

**Compatibility with current architecture:** These GA/GC/GR labels are proposed *workflow review gates*, not three interchangeable authorizations. Current [ARCHITECTURE.md](../ARCHITECTURE.md) remains authoritative: PUBLISH approval is not runtime DEPLOY permission; candidate deployment is not a release; a ContractRelease is provenance, not a DeploymentAuthorization; and protected CI/CD credentials are authoritative for runtime mutation. Future action-level authorize() checks restrict SemaPact-mediated operations; they cannot substitute for external IAM/branch protections or guarantee that an agent with direct platform credentials cannot bypass the tool. Design must prevent bypass by credential isolation.

Retain explicit effective-date semantics for mutation context. Do **not** adopt the gap analysis proposal to silently default a governance-semantic effective date to the current clock time; see [../GOVERNANCE_CONTEXT.md](../GOVERNANCE_CONTEXT.md).

## Extension and dependency seams

- **Check:** deterministic pure or delegated verifier with structured result and stable reason/fingerprint.
- **Action:** potentially effectful tool with declared operation class, target environment, permissions and evidence. Its public execution path checks workflow scope and governance before invocation, and relies on external IAM for actual target access.
- **Context:** read-only evidence accessor; external data is untrusted.
- **Review/Event provider:** external review and runtime event normalization.
- **RuntimeDriver:** readiness, observation, quality receipts plus optional pipeline-runner, lineage, schema deployment, projection and cost capabilities. Unsupported mandatory checks BLOCK, not silently PASS.
- **PipelineFrameworkDriver:** metadata-bound or code-bound adapter. Metadata-bound mode must not let agents edit framework runtime internals; unsupported intent yields an explicit capability-gap result.
- **AgentRunner:** replaceable external worker, not an LLM hosted within LangGraph.

Keep layering in one repository without reversing current semantic owners: immutable contract/governance/release kernel; runtime verification/adapters; optional loop orchestration and MCP/server surfaces. No dependency from lifecycle/domain policy to LangGraph or platform SDKs; base installation remains import-safe.

## Adopt, delegate, freeze

| Keep / invest | Delegate / stop duplicating | Freeze or defer |
| --- | --- | --- |
| GovernanceDecision, ChangeSet, immutable release and deployment artifacts, authorization boundaries | ODCS lint, standard diff primitives and executable DQ tests to Data Contract CLI wherever verified equivalent | Internal GE validation runtime and suite-export expansion |
| Independent exit checks, evidence provenance, loop state, step/action policies | Pipeline execution to Databricks/Lakeflow/DAB and framework plugins | New provider-specific DDL for pipeline-owned tables |
| Operational history, protected Git ledger, reconcile authority | Coding, self-repair and agent dispatch to external harnesses | Vendor-specific LLM enrichment, TUI and graph exporter extensions |
| Trusted profiles and narrow runtime adapters | Source extraction and source-system comparison to ingestion toolchains | Broad multi-platform support, server/dashboard before loop pilot |

Do not remove existing production-facing functionality merely because it is outside the target: freeze first, verify substitutes, then make a separate tested removal decision. The target architecture does not override existing documented runtime/release invariants.

## Delivery plan and open decisions

The sequence and exit criteria are maintained in [ROADMAP.md](ROADMAP.md). Implement **Phase 0 manual pilot first**, using an approved data contract with DQ rules, real pipeline work and independent verification evidence; do not commit to broad framework abstractions before observing real failures.

Open decisions: contract staging and in-pipeline receipt convention; verified minimum Data Contract CLI flags/versions; local checkpointer location; precise GA sealing scope; source-control-totals contract; and whether later non-contract engineering tasks require a broader run identity.
