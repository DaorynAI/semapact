# 🤖 SemaPact Agentic System & AI Skills

Welcome to the **SemaPact AI Agentic System**!

To guarantee high-quality code generation, secure data contract governance, and rigorous defensive coding, we provide built-in **AI Agent Skills** under the `.agents/skills/` directory.

## 🌟 What is this?
AI Coding Assistants (such as Google Gemini, Cursor, Claude, or GitHub Copilot) can dynamically load these skills to align their reasoning with SemaPact's core architectural guidelines.

## 📂 Active Skills (Flat Structure)
- [semapact-system](skills/semapact-system/SKILL.md): Core platform principles (e.g., Change-driven editing, immutable main contracts).
- [defensive-coding](skills/defensive-coding/SKILL.md): Strict exception handling, static typing, and test-mocking guidelines.
- [devops-workflow](skills/devops-workflow/SKILL.md): GitOps automation, release preparation, and version bump rules.
- [draft-workflow](skills/draft-workflow/SKILL.md): Draft contract save, load, and persistence logic.
- [lifecycle-policy](skills/lifecycle-policy/SKILL.md): Single Source of Truth for contract breaking changes, auto-deprecation, and lifecycle gating rules.
- [llm-enricher](skills/llm-enricher/SKILL.md): Core prompts, metadata provenance tagging, and Mocking policy for the LLM enrichment tools.
- [odcs-skills](skills/odcs-skills/SKILL.md): Upstream dependency alignment guidelines, custom properties, and deterministic GitOps sorting.
- [service-layer](skills/service-layer/SKILL.md): UI-independent service interfaces.

## 🛠️ How AI Assistants Use These Skills
If you are developing with an AI assistant, you can instruct it to:
> "Read the active agent skills in `.agents/skills/` before refactoring or implementing new modules."
