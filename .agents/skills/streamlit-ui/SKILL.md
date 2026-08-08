---
name: streamlit-ui
description: Detailed layout, design system (calm theme), UX principles, and presentation logic for the Streamlit single-page application. Apply this skill when modifying app.py, UI elements, or interactive components.
---

# SemaPact Streamlit UI Specification

This skill defines the design system, layout, and UX rules for the SemaPact Streamlit application.

## 1. Single-Page Architecture
- **Rule:** The UI is a single-page application with state-driven views.
- **Rule:** Do NOT implement sidebar-based navigation (remove any sidebar links for editor, merge, or analysis).
- **Rule:** All page navigation must be state-driven using session state:
  - `st.session_state.view_mode` (catalog, detail)
  - `st.session_state.selected_contract_id`
  - `st.session_state.contract` (single source of truth for current contract model)
  - `st.session_state.analysis_result`

## 2. Design System & Spacing
- **Theme:** Light, business-friendly, calm, low contrast.
- **Rule:** DO NOT use a dark theme or neon/high-intensity colors.
- **Colors:**
  - Background: `#F7F9FC`
  - Surface/Card Background: `#FFFFFF`
  - Border: `#E5E7EB`
  - Primary Accent: `#3B82F6` (blue)
  - Text: Heading `#111827`, Body `#374151`, Muted `#6B7280`
- **Status Badges:**
  - Active: `#10B981` (green)
  - Deprecated: `#F59E0B` (orange)
  - Breaking: `#EF4444` (red)
  - Draft: `#6B7280` (gray)
- **Spacing:** Enforce a clean `8px` / `16px` / `24px` spacing rhythm. Avoid dense, cluttered information grids.

## 3. UI Views & Component Architecture

### A. Catalog View (Default)
- Grid of Contract Cards.
- Each card displays: name, version, status badge, domain, tenant, tags, and description.
- Actions: **View Details** and **Edit** (disable editing buttons if user lacks write permissions).

### B. Detail View
- **Header:** Back button to Catalog, action buttons (Analyze Changes, Save).
- **Tabs:**
  - **Schema Tab:** Lists properties. Editable descriptions must use EXPANDABLE FIELD SECTIONS. No left-right layouts or dropdown field selectors. Read-only fields include type, required, lifecycleStatus.
  - **Quality Tab:** Quality rules table editor.
  - **Advanced Tab:** Read-only raw YAML view in an expander.
- **Analyze Panel:** Triggered on-demand, shows merge decisions, metrics, breaking change list (red), deprecated field list (orange), and an interactive diff expander.

## 4. Permissions & Safe Editing
- **Rule:** User can edit ONLY if they belong to the same tenant or are an admin.
- **Rule:** If the contract is read-only for the current user, display a read-only banner, disable editing inputs, and disable the Save button.
- **Rule:** The UI must NEVER implement business logic or merge engine operations directly. It must strictly delegate to the service layer.
