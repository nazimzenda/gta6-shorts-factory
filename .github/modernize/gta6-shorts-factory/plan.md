# Implementation Plan: GTA 6 Shorts Factory

**Date**: 2026-11-07 | **Spec**: `GTA6_SHORTS_FACTORY_AGENT_BRIEF.md`

## Summary

Build a local-first Founder Control Tower and rights-aware short-form media factory. The first implementation slice establishes a safe FastAPI foundation with local processing enabled and Everygen.ai, CUA, and publishing disabled by default. Later phases add persistence, dashboard UX, media processing, MCP adapters, guarded CUA, publishing, and analytics.

## Technical Context

**Language/Version**: Python 3.12+  
**Primary Dependencies**: FastAPI, Pydantic, Uvicorn, pytest  
**Storage**: SQLite for the first local slice; PostgreSQL and object storage before multi-user deployment  
**Testing**: pytest and FastAPI TestClient  
**Target Platform**: Linux local development first; containerized private deployment later  
**Performance Goals**: Non-blocking asynchronous jobs; local processing should continue when remote providers are unavailable  
**Constraints**: Rights validation, founder approval for consequential actions, no rate-limit bypass, no secrets in source, explicit errors

## Constitution Check

- Founder remains final authority: PASS. The initial API exposes no publishing or paid-provider action.
- Local-first processing: PASS. Local processing is enabled by default.
- MCP before CUA: PASS. Integration adapters will be designed around MCP; CUA remains disabled.
- Auditable actions: PASS for the foundation; audit persistence is a later task.
- Rights-aware production: PASS in design; rights service is a required foundational phase.

## Applied Guidelines

- FastAPI request/response models use Pydantic types and explicit response models.
- Configuration is environment-driven with safe defaults.
- Provider integrations use an adapter boundary and must not leak credentials.
- Long-running media operations belong in workers rather than request handlers.

## Requirements

- **REQ-001**: Founder can view company, department, worker, task, approval, cost, and publishing state.
- **REQ-002**: AI CEO can decompose founder objectives into governed department tasks.
- **REQ-003**: Only rights-cleared source media can enter production.
- **REQ-004**: Local media processing works without Everygen.ai.
- **REQ-005**: Everygen.ai is optional, quote-aware, and provider-isolated.
- **REQ-006**: MCP is the primary integration layer.
- **REQ-007**: CUA is isolated, allowlisted, auditable, revocable, and never a rate-limit bypass.
- **REQ-008**: Paid generation and final publishing require founder approval.
- **REQ-009**: Production, publishing, costs, and analytics are auditable.
- **REQ-010**: The system can pause work and recover from failed jobs.

## Implementation Steps

### Step 1: [Cross-cutting] Establish safe application foundation

- **Requirements**: REQ-001, REQ-004, REQ-008
- **Design inputs**: Architecture diagram, sections "Key Architectural Decisions" and "Permission model"
- **Description**: Create typed API foundation, environment configuration, health checks, dashboard summary, tests, and safe integration defaults. Completed in the initial slice.

### Step 2: [Cross-cutting] Add persistence and audit primitives

- **Requirements**: REQ-001, REQ-003, REQ-009, REQ-010
- **Design inputs**: Architecture "Data Schema" and "Trust boundaries"
- **Description**: Add database migrations, repositories, asset metadata, rights records, approvals, task events, cost events, and append-only audit events.

### Step 3: [Cross-cutting] Build Founder Control Tower

- **Requirements**: REQ-001, REQ-002, REQ-008, REQ-010
- **Design inputs**: Agent brief "Founder Control Tower dashboard"
- **Description**: Add frontend dashboard for departments, illustrated workers, tasks, approvals, integration status, costs, emergency stop, and reports.

### Step 4: [Cross-cutting] Implement local media pipeline

- **Requirements**: REQ-003, REQ-004, REQ-009
- **Design inputs**: Agent brief "Production pipeline"
- **Description**: Add ingest, hashing, ffprobe inspection, transcription, scene analysis, highlight candidates, captions, vertical rendering, and quality checks.

### Step 5: [Cross-cutting] Implement AI CEO and worker orchestration

- **Requirements**: REQ-002, REQ-009, REQ-010
- **Design inputs**: Agent brief "Virtual enterprise model" and architecture "Component Relationships"
- **Description**: Add department queues, worker capabilities, dependency-aware tasks, retries, escalation, pause, dead-letter handling, and evidence.

### Step 6: [Cross-cutting] Implement MCP gateway and Everygen adapter

- **Requirements**: REQ-005, REQ-006, REQ-008, REQ-009
- **Design inputs**: Agent brief "MCP versus CUA" and "Everygen.ai integration"
- **Description**: Add MCP server registry, scoped tool calls, provider capability discovery, quote-before-spend, asynchronous job tracking, idempotency, and a mocked provider test suite. Verify live Everygen documentation before enabling the adapter.

### Step 7: [Cross-cutting] Implement guarded CUA broker

- **Requirements**: REQ-007, REQ-008, REQ-009, REQ-010
- **Design inputs**: Architecture "CUA workflow" and "Trust boundaries and controls"
- **Description**: Add isolated observe and draft sessions, domain allowlists, capability tokens, action evidence, timeouts, emergency stop, and founder confirmation. Keep publishing capability disabled until policy review passes.

### Step 8: [Cross-cutting] Add publishing and analytics

- **Requirements**: REQ-001, REQ-008, REQ-009
- **Design inputs**: Agent brief "Stage F: Approval and publishing"
- **Description**: Add official platform adapters, schedule reconciliation, post IDs, analytics snapshots, cost reports, and founder-approved publishing locks.

## Project Structure

```text
app/
  main.py                 # FastAPI entrypoint
  config.py               # Environment configuration
  models.py               # Typed API/domain models
  api/                    # Dashboard and domain routes
  domain/                 # Business rules and services
  persistence/            # Database repositories and migrations
  workers/                # Media and department workers
  integrations/           # MCP, Everygen, platform adapters
  cua/                    # Isolated CUA broker
tests/
  unit/
  integration/
  contract/
web/                      # Founder Control Tower frontend
data/                     # Local-only runtime data, ignored by git
```

## Testing Strategy

- **appType**: Mixed API and SPA with asynchronous workers.
- **Critical user journeys**:
  1. Founder views safe dashboard state.
  2. Source asset is blocked when rights are missing or expired.
  3. Local media job runs with Everygen disabled.
  4. Paid provider job cannot run without an approval ID.
  5. CUA session stops on disallowed domain or emergency stop.
- **primaryValidationStack**: pytest, FastAPI TestClient, SQLite test database, FFmpeg fixture media, mocked provider and platform adapters.
- **fallbackMatrix**:
  - `database-tier`: PostgreSQL container -> SQLite local test database.
  - `media-tier`: FFmpeg installed -> fixture-only metadata tests.
  - `browser-tier`: Playwright -> API contract tests for the first backend slice.
- **Environment requirements**: Python 3.12+, FFmpeg, Node.js for the dashboard phase, Docker for PostgreSQL and object storage integration tests.
- **knownGaps**: Provider and publishing tests remain mocked until accounts and official contracts are approved.
- **Test data strategy**: deterministic fixture media, isolated test database per run, no real creator or platform credentials.
- **Acceptance criteria**: all foundation tests pass; safety defaults are verified; no external action is possible without approval.
- **Validation review expectations**: confirm routes, defaults, permission gates, audit events, and explicit error responses.

## Task Breakdown

- [x] T001 [Plan:1.1] Create Python package, safe configuration, health endpoint, dashboard summary endpoint, and baseline tests.
- [x] T002 [P] [Plan:2.1] Add persistence configuration, migrations, repositories, and audit event model.
- [x] T003 [P] [Plan:2.2] Add source asset, rights record, approval, and task domain services.
- [x] T004 [Plan:3.1] Build the eleven-view Founder Control Tower dashboard shell, including the department interaction map, and wire live API/WebSocket state.
- [x] T005 [Plan:4.1] Implement local ingest, hashing, ffprobe inspection, and rights gate.
- [x] T006 [Plan:4.2] Implement transcription, highlight candidates, captions, vertical rendering, and QC.
- [x] T007 [Plan:5.1] Implement AI CEO planning, worker capabilities, queues, retries, pause, and dead-letter handling.
- [x] T008 [Plan:6.1] Implement MCP registry, scoped tool calls, and audit events.
- [x] T009 [Plan:6.2] Implement Everygen provider adapter with quote-before-spend and mocked async jobs.
- [x] T010 [Plan:7.1] Implement isolated CUA broker with observe and draft modes, allowlists, evidence, and emergency stop.
- [x] T011 [Plan:8.1] Implement publishing approval locks, dry-run adapter, scheduling records, reconciliation, and analytics snapshots; live official adapters remain gated.
- [x] T012 [Plan:8.2] Add integration, security, recovery, and end-to-end acceptance tests.

## Requirement Mapping

| REQ ID | Description | Plan Items | Implementation Evidence |
|---|---|---|---|
| REQ-001 | Founder sees enterprise state | 1.1, 3.1, 8.1 | `app/main.py`, `web/`, dashboard routes |
| REQ-002 | CEO assigns governed work | 3.1, 5.1 | CEO service, task queue, worker records |
| REQ-003 | Rights gate production | 2.1, 2.2, 4.1 | rights records, ingest gate, tests |
| REQ-004 | Local processing works independently | 1.1, 4.1, 4.2 | FFmpeg pipeline and disabled-provider tests |
| REQ-005 | Everygen is optional and quote-aware | 6.2 | provider adapter and quote tests |
| REQ-006 | MCP is primary integration | 6.1, 6.2 | MCP registry and tool call records |
| REQ-007 | CUA is guarded and auditable | 7.1 | CUA broker, sessions, evidence, emergency stop |
| REQ-008 | Founder approval gates spend and publishing | 1.1, 6.2, 7.1, 8.1 | approval service and capability checks |
| REQ-009 | Actions and outcomes are auditable | 2.1, 4.2, 5.1, 6.1, 7.1, 8.1 | audit events, job evidence, analytics |
| REQ-010 | Pause and recovery are supported | 2.1, 5.1, 7.1, 8.2 | queue controls, dead-letter handling, recovery tests |
