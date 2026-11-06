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
| Claude Code | `/prospec-<name>` |

Each Skill's description and trigger words are surfaced automatically from its `SKILL.md` frontmatter, so identify the matching bare `prospec-<name>` Skill.

## Session Start

At the start of a session, run `prospec status` — it deterministically reports each in-progress
change's name, current node, suggested next step, and blocking gates (the executable copy of
`prospec/ai-knowledge/_status-lifecycle.md`). The prospec CLI (version ≥ 2.11.0)
is a required file for the prospec skills: when it is missing or too old, STOP and install/upgrade
the standalone executable before running any skill — never substitute manual steps.

## Working with This Project

**Constraint**: Follow the L0-L3 progressive loading model. Always read `prospec/index.md` (L1) first. Never load L2 (Module READMEs) or L3 (Source Code) proactively before identifying the required modules.

**Station Transition Protocol**: The SDD workflow advances through stations. On advancing to ANY new station — whether `prospec status` routed you there or you cascaded to it autonomously — run `prospec status` first: it names the station's canonical `prospec-<name>` Skill, its reference map, and the resolved skill file as a separate fallback. Load that station's instructions BEFORE taking any station action:

- Invoke — or re-invoke — the named Skill through this host's own skill mechanism, on every transition and re-entry. When that mechanism is unavailable, read the fallback file under `.claude/skills/` instead.

Then read that station's references at the phases it names; loading a station never means its references arrived. If neither route yields the station's instructions, STOP and name what is missing — never act on remembered rules, and never skip an entry gate or a receipt. Accumulated context is no substitute: a long session's diffs and logs dilute the initial instructions.

**Evidence Recording Order**: Recording evidence is the last mutation: every planned edit to the evidence snapshot's inputs lands before the final test record and review baseline; an edit afterward reopens them.

**Checkpoint Correction Capture Protocol**: At natural reflection points — at session end, or before archiving a change — review the developer corrections you received this session and record each *generalizable* one via `prospec learn upsert` (a cross-cutting architecture, type-contract, testing, or security rule — never a one-off mock or business-string tweak; the deciding heuristic lives in the `prospec-learn` Skill's promotion-format reference under `.claude/skills/`, which you read with your file-reading tool rather than guessing from memory), naming its modules from `prospec/ai-knowledge/module-map.yaml` and terms from `prospec/ai-knowledge/_glossary.md`, with the `description` in the language the correction was given. Stay silent — do not interrupt the conversation or ask a blocking question — and surface a single line only when the command reports a promotion suggestion. Keep this ledger write a separate concern; never fold it into a feature commit.

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
