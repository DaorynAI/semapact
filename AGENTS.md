# 🤖 SemaPact AI Agent Guidelines

Welcome, AI Agent! You are working on **SemaPact**, an open-source, enterprise-level lifecycle governance platform for Open Data Contracts (ODCS).

To ensure high-quality and consistent code generation, please adhere to the following rules:

## 1. Architectural Alignment
SemaPact is a change-driven (not CRUD) system that enforces GitOps workflows, immutable main contracts, and user-scoped drafts.
- **Always read [`ARCHITECTURE.md`](./ARCHITECTURE.md)** before designing new features, adding state, or modifying core modules.

## 2. Load Your Skills
We maintain specialized instructions for you in the `.agents/skills/` directory. 
- **Always read [`.agents/README.md`](./.agents/README.md)** at the start of a session to understand the available skills.
- Load the specific `SKILL.md` file relevant to your current task (e.g., if you are touching UI, read the `streamlit-ui` skill; if touching validation, read `lifecycle-policy`).

## 3. Core Principles
1. **Defensive Coding**: All new code must be fully type-hinted and handle edge cases gracefully. Do not swallow exceptions silently.
2. **Configuration over Environment Variables**: Favor adding user configuration to `ConfigManager` (which resolves from `.semapact.yaml`) rather than hardcoding `os.environ` reads, unless it's a dynamic CI runner variable.
3. **Preserve Main Contracts**: Canonical contracts in `contracts-main` or the base path should never be overwritten blindly. Use the `merge_engine`.

## 4. Agent Working Style
As an AI contributing to an enterprise-grade open-source project, your execution must be flawless and maintainable:
1. **Plan Before Code**: Always think through the architectural implications and edge cases before writing a single line of code. If a change is complex, propose an implementation plan to the user first.
2. **Make It Simple**: Strive for elegant, minimalist solutions. Avoid over-engineering, unnecessary abstractions, or introducing heavy external dependencies unless absolutely required.
3. **Double Check Your Work**: Never assume your code works on the first try. Always double-check your syntax, type hints, and logic. Where possible, write or run tests to verify your changes.

## 5. Testing
- If you modify business logic in `semapact/core` or `semapact/lifecycle`, you must ensure backward compatibility.
- Ensure that the CLI (`semapact/interfaces/cli.py`) and TUI (`semapact/tui/app.py`) are kept in sync when introducing new configuration parameters.

## 6. Behavioral Guidelines (CLAUDE.md)

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 6.1 Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 6.2 Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 6.3 Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 6.4 Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
