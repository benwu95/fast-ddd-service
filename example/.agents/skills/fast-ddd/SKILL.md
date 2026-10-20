---
name: fast-ddd
description: Build and change this fast-ddd service, including bounded contexts, aggregates, domain commands, batch operations, event handlers, MQ consumers, background tasks and cron schedules, following the fast-ddd kernel's layering and conventions; also sets up secret protection for the agent host.
---

# fast-ddd

This skill is written for fast-ddd-kernel `0.1.0`.

- Kernel version: `0.1.0`
- Kernel lock: `../uv.lock`

## Step 1: Check the kernel version

Before reading or changing anything else, run `make kernel-version` from the service root, the directory that contains `.copier-answers.yml`.

- The command succeeds: continue.
- The output contains `fast-ddd kernel version check failed`: stop without modifying any file. The locked kernel does not match the version this skill describes, or the lock is missing, so the rules and reference code may be wrong for this service. Show the output to the user and point them to the section "可選的骨架更新" in `docs/template-operations.md`, which updates the template and the kernel together.
- It fails without that message: stop, show the output and say that the check could not run, for example because `uv` could not start. This is not a version mismatch. `make` exits with 2 whenever its recipe fails, so judge by the message, not by the exit code.

## How to use this skill

- Paths that start with `references/` are relative to the directory that contains this SKILL.md. Every other path, such as `app/...`, `tests/...` or `docs/template-operations.md`, is relative to the service root.
- Pick the workflow that matches the request, read its file, and load only the rules and reference code it lists.
- `references/example/` is a read-only copy of the framework's billing reference service. Copy its patterns into this service's own files; never import from it or edit it.
- Generate only what the user asked for. A new aggregate gets list, get, create, PATCH and delete; anything else needs an explicit request.
- A code workflow is done when `make check` passes from the service root, including the tests the workflow requires.

## Workflows

| Request | Workflow |
|---|---|
| Add a bounded context | `references/workflows/bounded-context.md` |
| Add an aggregate with default CRUD | `references/workflows/aggregate.md` |
| Add a domain command such as void | `references/workflows/domain-command.md` |
| Add a batch operation such as batch-void | `references/workflows/batch-operation.md` |
| React to a domain event | `references/workflows/event-handler.md` |
| Consume messages from another service | `references/workflows/mq-consumer.md` |
| Add a background task or a cron schedule | `references/workflows/background-task-and-cron.md` |
| Set up secret protection for this agent host | `references/workflows/secret-protection.md` |

## Rules

| Topic | File |
|---|---|
| Layers, dependencies and shared code | `references/rules/layering.md` |
| Time handling and serialization | `references/rules/time-and-serialization.md` |
| Routes, status codes, error codes and naming | `references/rules/api.md` |
| Tenant isolation, authentication and authorization | `references/rules/security.md` |
| Required tests per aggregate | `references/rules/testing.md` |

## Design decisions

Read `references/decisions.md` when a workflow points to it or when a choice is not settled by the rules: it records the reasoning the code alone does not show.
