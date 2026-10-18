# Project Constitution: fast-ddd-service

> This document defines the guiding principles and constraints for the **fast-ddd-service** project.
> AI Agents and developers should consult this document before making architectural or design decisions.
>
> The principles below are **starter rules** seeded from your tech stack — edit, add, or remove to fit your project. Each carries an RFC-2119 severity (**MUST** / **SHOULD** / **MAY**) that `prospec-verify` grades against: violating a MUST → FAIL, SHOULD → WARN; a MAY is advisory (informational, does not affect the grade).

## Principles

### [MUST] Language Policy

**Description**: All generated documents — change artifacts and their archived summaries (`.prospec/changes/**`, `.prospec/archive/**`, `.prospec/abandoned/**`, `prospec/specs/_archived-history/**`) and the trust zone (`prospec/CONSTITUTION.md`, `prospec/README.md`, `prospec/index.md`, `prospec/specs/product.md`, `prospec/specs/features/**`, `prospec/ai-knowledge/**`) — are written in Traditional Chinese (Taiwan); code, identifiers, technical terms, and git commit messages stay English.

**Rationale**: The project owner reads both the change narrative and the trust zone in Traditional Chinese (Taiwan), while code, identifiers, technical terms, and git commit messages stay English so the project reads like the ecosystem it ships into. Both this rule and the agent entry config are generated from one resolved path set, so the two cannot drift into contradicting each other.

**Verify**: stations: all; Files under `.prospec/changes/**`, `.prospec/archive/**`, `.prospec/abandoned/**`, `prospec/specs/_archived-history/**` and `prospec/CONSTITUTION.md`, `prospec/README.md`, `prospec/index.md`, `prospec/specs/product.md`, `prospec/specs/features/**`, `prospec/ai-knowledge/**` are written in Traditional Chinese (Taiwan); code, technical terms, and commit messages are in English.

---
### [MUST] Authenticated API endpoints

**Description**: All API endpoints require authentication unless explicitly public.

**Rationale**: Unauthenticated endpoints are the most common source of data exposure.

**Verify**: Each route handler resolves an auth dependency/decorator.

---
### [MUST] Tested public functions

**Description**: Every public function ships with unit tests.

**Rationale**: Untested code regresses silently; tests encode intended behavior.

**Verify**: Each public symbol has a corresponding test.

---
### [SHOULD] Clean architecture boundaries

**Description**: Business logic lives in domain/service layers, not in route handlers.

**Rationale**: Keeping I/O out of domain logic keeps it testable and reusable.

**Verify**: Route handlers call a service and contain no direct DB/ORM/query calls.

---
### [SHOULD] Structured API errors

**Description**: API errors follow a consistent structured format (e.g. RFC 7807).

**Rationale**: A uniform error contract lets clients handle failures predictably.

**Verify**: Error responses include a stable type/title/status shape.

---
<!-- Add your own principles below. Tag each with [MUST] / [SHOULD] / [MAY] so verify can grade them. -->

### [MUST] Python 命名與 wire contract

**Description**: Python domain、dataclass 與 handler 屬性使用 snake_case；API request／response JSON 及 MQ envelope／業務 payload 的固定欄位使用 camelCase。DB 欄位與內部 domain_event body 使用 snake_case。任意業務 map key 保留原樣，kernel 在序列化與反序列化邊界集中處理固定欄位的命名轉換。

**Rationale**: 本專案提供 Python skill，同時支援 Python、C# 與 Node.js 後端 consumer。讓 Python 開發者以原生命名操作具型別的資料，並以固定的跨語言 wire contract 交換訊息；此方案由專案擁有者於 2026-10-18 確認。

**Verify**: stations: all; 需求與規劃明訂各邊界的命名；contract tests 以真實 producer 輸出驗證 consumer 可接收多字與巢狀欄位，並確認任意 map key 保留原樣、Python 屬性與 domain_event body 維持 snake_case。

---

## Quality Standards

<!-- Define quality requirements (testing, documentation, performance) -->

- **Testing**: [e.g., "All public functions must have unit tests"]
- **Documentation**: [e.g., "All public APIs must have doc comments"]

---

> Last updated: 2026-10-17T18:12:00.716Z
