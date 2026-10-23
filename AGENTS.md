<!-- prospec:auto-start -->
# fast-ddd-service

> AI-augmented project with Prospec Skills and structured AI Knowledge

## Tech Stack

- **Language**: python
- **Package Manager**: uv

## Language Policy

All generated documents — change artifacts (`.prospec/changes/**`, `.prospec/archive/**`, `.prospec/abandoned/**`, `prospec/specs/_archived-history/**`) and the trust zone (`prospec/CONSTITUTION.md`, `prospec/README.md`, `prospec/index.md`, `prospec/specs/product.md`, `prospec/specs/features/**`, `prospec/ai-knowledge/**`) — are written in **Traditional Chinese (Taiwan)**, and requests may be phrased in it; code, identifiers, technical terms, and git commit messages stay English (see the Constitution's Language Policy rule, generated from this same path set).

## Core Resources

### Constitution
Project principles and constraints: [`prospec/CONSTITUTION.md`](prospec/CONSTITUTION.md)

### AI Knowledge Base
Module index and project structure (L1-L3 navigation): [`prospec/index.md`](prospec/index.md)

### Coding Conventions
Coding standards and best practices: [`prospec/ai-knowledge/_conventions.md`](prospec/ai-knowledge/_conventions.md)
Diagram conventions: [`prospec/ai-knowledge/_diagram-conventions.md`](prospec/ai-knowledge/_diagram-conventions.md)
Project glossary and domain terms: [`prospec/ai-knowledge/_glossary.md`](prospec/ai-knowledge/_glossary.md)

## Available Prospec Skills

Prospec Skills use bare `prospec-<name>` as their canonical identity. Use the host-specific guidance below only when you want to invoke a Skill explicitly; descriptions and trigger words continue to support implicit discovery.

## Invoking a Prospec Skill

| Host | Explicit invocation |
|------|---------------------|
| Codex | `$prospec-<name>` |
| Antigravity | Mention the bare Skill name or select it from the Skills browser. `prospec-<name>` |

This project ships with the following Prospec Skills:

### prospec-explore

Explore - Requirement exploration, problem investigation, and solution comparison partner — clarifies before a Story exists, not the Story writer itself. Not for: 撰寫 Story; 一般腦力激盪.

**Type**: Lifecycle
**Triggers**: explore, compare, investigate, unsure, clarify, 探索, 比較, 調查, 不確定, 釐清

### prospec-new-story

New Story - Create change requests by guiding User Story and acceptance criteria definition — the SDD entry station, not a generic issue or ticket writer. Not for: 一般 issue 撰寫; 草擬工單.

**Type**: Planning
**Triggers**: new feature, requirement, user story, 新功能, 需求, 使用者故事
**References**: `.agents/skills/prospec-new-story/references/`

### prospec-plan

Plan Implementation - Convert User Story into technical implementation plan (plan.md) and change specification (delta-spec.md) — the SDD plan station, not ad-hoc architecture discussion. Not for: 臨時架構討論; UI 設計.

**Type**: Planning
**Triggers**: plan, architecture, technical plan, 規劃, 架構, 技術規劃
**References**: `.agents/skills/prospec-plan/references/`

### prospec-design

Design Phase - Generate visual and interaction specs from proposal (Generate Mode) or extract specs from existing design tools (Extract Mode). Supports pencil/Figma/Penpot/HTML platforms. UI scope only — not architecture design (that is the plan station). Not for: 架構設計; API 設計.

**Type**: Planning
**Triggers**: UI spec, generate design, extract design, UI 規格, 產生設計, 擷取設計
**References**: `.agents/skills/prospec-design/references/`

### prospec-tasks

Break Down Tasks - Decompose implementation plan into an actionable task checklist (tasks.md) — the SDD station after plan, not a generic todo tool. Not for: 一般待辦清單; 個人任務追蹤.

**Type**: Planning
**Triggers**: break down, task list, work items, how to split, 拆解, 任務清單, 工作項目, 如何拆分
**References**: `.agents/skills/prospec-tasks/references/`

### prospec-ff

Fast-Forward Planning - Generate complete planning artifacts in one pass (Story → Plan → Tasks) — for clear requirements, not exploration. Not for: 模糊的需求; 需求探索.

**Type**: Planning
**Triggers**: fast-forward, ff, all at once, 快轉, 一次產生, 一次完成
**References**: `.agents/skills/prospec-ff/references/`

### prospec-implement

Implementation - Execute tasks from the task list, implementing features one by one — driven by tasks.md, not free-form coding without a task list. Not for: 沒有 tasks.md 就寫程式; 變更以外的快速修正.

**Type**: Execution
**Triggers**: implement, start coding, write code, 實作, 開始寫程式, 寫程式
**References**: `.agents/skills/prospec-implement/references/`

### prospec-review

Adversarial Code Review → Fix Loop - Between implement and verify, an independent fresh-context reviewer audits the whole change diff; verifier-confirmed criticals are auto-fixed, majors are proposed, and a spec-aware lens checks delta-spec/dependency-direction — the SDD station between implement and verify, not ad-hoc PR review. Not for: 臨時 PR 審查; 一般程式碼評論.

**Type**: Execution
**Triggers**: code review, adversarial review, find bugs, 程式碼審查, 對抗式審查, 找 bug
**References**: `.agents/skills/prospec-review/references/`

### prospec-verify

Verify Implementation - Run 5+1 dimension audit (tasks, spec compliance, constitution, knowledge-implementation consistency, tests, design consistency) and assign quality grade (S/A/B/C/D) — the SDD gate before archive, not a plain test run. Not for: 只執行測試; 一般 QA.

**Type**: Execution
**Triggers**: verify, audit, quality check, 驗證, 稽核, 品質檢查
**References**: `.agents/skills/prospec-verify/references/`

### prospec-knowledge-generate

Generate AI Knowledge - Read raw-scan.md, analyze project structure, autonomously decide module boundaries, and produce Recipe-First module READMEs and index — first-time seeding, not the incremental update after a change. Not for: 增量知識庫更新; 編輯單一 README.

**Type**: Lifecycle
**Triggers**: generate knowledge, analyze project, module split, 產生知識庫, 分析專案, 模組切分

### prospec-archive

Archive Changes - Archive completed changes, generate summary, sync requirements to feature specs, and gate archiving on Knowledge sync — the SDD terminal station, not git tagging or a release. Not for: git 標籤; 發佈版本.

**Type**: Lifecycle
**Triggers**: archive, spec sync, finalize change, 封存, 規格同步, 完成變更
**References**: `.agents/skills/prospec-archive/references/`

### prospec-knowledge-update

Incremental Knowledge Update - Parse delta-spec.md to identify affected modules, scan source code, and update module README, index.md, and module-map.yaml incrementally — after a change, not the first-time knowledge scan. Not for: 首次產生知識庫; 完整重新掃描.

**Type**: Lifecycle
**Triggers**: knowledge update, incremental update, sync knowledge, update docs, 知識庫更新, 增量更新, 同步知識庫, 更新文件

### prospec-backfill-spec

Backfill Spec - Reverse-extract a behavioral Feature Spec draft from existing brownfield code (source = code, not a design tool) for features/capabilities with no spec coverage. Records behavior, never intent; stages a draft for human verify-and-promote and never writes the trust zone. Not for: 從設計工具擷取; 撰寫新需求.

**Type**: Lifecycle
**Triggers**: backfill spec, spec from code, brownfield, document existing code, 回填規格, 從程式碼產生規格, 既有專案, 為既有程式碼補文件
**References**: `.agents/skills/prospec-backfill-spec/references/`

### prospec-promote-backfill

Promote Backfill - Formalize a reviewed backfill-draft.md into the backfill change scaffold (proposal.md + delta-spec.md + metadata.yaml with scale: backfill, status: implemented) so brownfield behavior can graduate through verify → archive. A light scale like quick — no hollow plan.md/tasks.md; the single, repeatable draft→scaffold step; never writes the trust zone — promotion only, not the draft extraction itself. Not for: 擷取草稿; 寫入信任區.

**Type**: Lifecycle
**Triggers**: promote backfill, formalize backfill, backfill to delta-spec, promote draft, 提升回填, 正式化回填, 回填轉 delta-spec, 提升草稿
**References**: `.agents/skills/prospec-promote-backfill/references/`

### prospec-learn

Feedback Promotion Pipeline - Collect session corrections, repeated verify FAILs and recurring review criticals into a version-controlled lessons ledger; score them with an explicit, reproducible rule (frequency + impact modules); and promote - only with explicit human approval - across three tiers (accumulating ledger -> team playbook -> Constitution rule) — a ledger for recurring lessons, not a one-off note taker. Not for: 一次性筆記; 個人提醒.

**Type**: Lifecycle
**Triggers**: learn, promote lesson, playbook, 學習, 提升教訓, 團隊手冊
**References**: `.agents/skills/prospec-learn/references/`


## Session Start

At the start of a session, run `prospec status` — it deterministically reports each in-progress
change's name, current node, suggested next step, and blocking gates (the executable copy of
`prospec/ai-knowledge/_status-lifecycle.md`). The prospec CLI (version ≥ 2.9.0)
is a required file for the prospec skills: when it is missing or too old, STOP and install/upgrade
the standalone executable before running any skill — never substitute manual steps.

## Working with This Project

**Constraint**: Follow the L0-L3 progressive loading model. Always read `prospec/index.md` (L1) first. Never load L2 (Module READMEs) or L3 (Source Code) proactively before identifying the required modules.

**Station Transition Protocol**: The SDD workflow advances through stations. On advancing to ANY new station — whether `prospec status` routed you there or you cascaded to it autonomously — run `prospec status` first: it names the station's canonical `prospec-<name>` Skill, its reference map, and the resolved skill file as a separate fallback. Load that station's instructions BEFORE taking any station action:

- Read the named station's `SKILL.md` — the fallback path under `.agents/skills/` — on every transition and re-entry.

Then read that station's references at the phases it names; loading a station never means its references arrived. If that read does not yield the station's instructions, STOP and name what is missing — never act on remembered rules, and never skip an entry gate or a receipt. Accumulated context is no substitute: a long session's diffs and logs dilute the initial instructions.

**Checkpoint Correction Capture Protocol**: At natural reflection points — at session end, or before archiving a change — review the developer corrections you received this session and record each *generalizable* one via `prospec learn upsert` (a cross-cutting architecture, type-contract, testing, or security rule — never a one-off mock or business-string tweak; the deciding heuristic lives in the `prospec-learn` Skill's promotion-format reference under `.agents/skills/`, which you read with your file-reading tool rather than guessing from memory), naming its modules from `prospec/ai-knowledge/module-map.yaml` and terms from `prospec/ai-knowledge/_glossary.md`, with the `description` in the language the correction was given. Stay silent — do not interrupt the conversation or ask a blocking question — and surface a single line only when the command reports a promotion suggestion. Keep this ledger write a separate concern; never fold it into a feature commit.

1. **Before starting**: Read the Constitution to understand project principles
2. **Understand the structure**: Consult the AI Knowledge Index to grasp the module architecture
3. **Coding standards**: Follow the style guide in the Conventions document
4. **Use Skills**: Trigger dedicated workflows via their bare `prospec-<name>` identity
5. **Module dependencies**: Check `prospec/ai-knowledge/module-map.yaml` before modifying

## Notes

- This file is Layer 0 (always loaded) — keep it lean and point to other resources
- Skills are Layer 1-2 — detailed instructions load on demand
- The Knowledge Base is on-demand — load according to the scope of work
<!-- prospec:auto-end -->

<!-- prospec:user-start -->
<!-- Add your own project-specific instructions below. This section is preserved across `prospec agent sync`. -->
<!-- prospec:user-end -->
