# Phase 0 Decision Report

**Project:** GTA 6 Shorts Factory  
**Date:** 2026-11-07  
**Status:** Local MVP implemented; external integrations deliberately disabled or mocked pending verification.

> This report records the stack decisions, hardware assumptions, license checks, security risks, and MVP boundary. It does not claim that Everygen.ai, MCP transports, CUA browser drivers, or platform publishing APIs have been verified live. Those integrations require official documentation review and founder approval before activation.

---

## 1. Environment audit

| Item | Observed |
|---|---|
| Operating system | Linux |
| Python | 3.14.4 |
| Node.js | v26.8.1 (not required for the dashboard; no build step) |
| SQLite | 3.46.1 (Python runtime) |
| FFmpeg / ffprobe | 8.0.1-3ubuntu2 |
| GPU | NVIDIA GeForce RTX 2070, 8 GB VRAM |
| Memory | 30 GiB total, ~15 GiB available during audit |
| Free disk | ~64 GB on the project volume |
| Project size | Small; generated media and SQLite dominate runtime storage |

The GPU is available for local Whisper inference if `faster-whisper` is installed. The shipped prototype does not require it; transcription falls back to manual transcript attachment with an explicit status.

---

## 2. Selected stack

| Layer | Choice | Reason |
|---|---|---|
| Dashboard | Vanilla HTML/CSS/ES2022 served by FastAPI | Zero build step, local-first, easy audit, no Node runtime dependency |
| API | FastAPI + Pydantic v2 | Typed validation, OpenAPI docs, first-class WebSocket support |
| Persistence | SQLite with migration-aware schema | Single-founder local system of record; portable backup |
| Queue | In-process task records + explicit CEO tick / run endpoints | Predictable local execution; no hidden background spending |
| Media | FFmpeg / ffprobe | Ubiquitous, scriptable, local, testable |
| Transcription | Optional faster-whisper / whisper | Local inference; explicit unavailable/error states |
| Captions | SRT sidecar + optional FFmpeg drawtext burn-in | Readable captions without a fragile mandatory font pipeline |
| Provider adapter | Everygen mock adapter | Quote-before-spend contract; no unverified network calls |
| Integration registry | MCP server/tool registry + hashed call audit | MCP is the control plane; live transport gated |
| CUA | Guarded broker only | Allowlist, tokens, action limits, evidence, emergency stop |
| Publishing | Dry-run adapter with approval locks | Prevents accidental live posting; platform APIs not integrated |
| Tests | pytest + FastAPI TestClient + FFmpeg fixture | End-to-end API, security, and media coverage |

### Why not React/Next.js for this slice

The brief allows React/Next.js. A vanilla SPA keeps the first release runnable with one Python process, no npm install, no bundler, and no frontend supply chain. The API is fully typed and the UI is isolated in `app/static/`, so a React migration can happen without touching domain logic.

### Why SQLite first

The prototype is explicitly local and single-founder. SQLite keeps backup/restore trivial and avoids a service dependency. The repository abstraction and migration helpers make a PostgreSQL move possible. PostgreSQL, Redis, and object storage remain the production direction once multi-user or high-volume operation begins.

---

## 3. License and dependency review

| Dependency | License / status | Notes |
|---|---|---|
| FastAPI | MIT | Permissive |
| Starlette | BSD-3-Clause | Permissive |
| Uvicorn | BSD-3-Clause | Permissive |
| Pydantic | MIT | Permissive |
| python-multipart | Apache-2.0 | Uploads |
| pytest / httpx | MIT / BSD-3-Clause | Development only |
| SQLite | Public domain | Embedded |
| FFmpeg / ffprobe | LGPL/GPL depending on build | Not redistributed; invoked as a local executable. Confirm distribution obligations before packaging |
| Whisper / faster-whisper | MIT | Optional, not installed by default |
| Everygen MCP | Not verified | Do not vendor or claim compatibility until official docs and license are checked |

No external service account, paid credit, credential, platform token, or browser automation driver is bundled.

---

## 4. Security and policy risks

| Risk | Control in this build |
|---|---|
| Unknown-rights footage enters production | Rights gate on analysis, render, QC, and publishing; expiry and platform checks; founder approval |
| Paid provider spend without consent | Everygen disabled by default; quote creates approval; job requires approved quote; budget checked |
| Provider job duplication | Request hash + existing-job lookup; publishing uses idempotency keys |
| Automatic publishing | `final_video` and `publish_final` approvals are both required; live mode is not implemented |
| CUA misuse | Disabled default; domain allowlist; per-session token; observe/draft only; action caps; expiry; evidence; no publish action |
| MCP tool misuse | Risk-scoped registry; high-risk tools require approval; live transport disabled |
| Emergency incident | Global emergency stop blocks all mutating API calls with HTTP 423 and stops CUA sessions |
| Hidden failures | Task events, provider errors, render errors, QC reports, audit events, and dashboard alerts are explicit |
| Secret leakage | Credential fields store references, not raw secrets; `.env` ignored; no tokens in source |
| Multi-user exposure | Not supported in this release; local binding only by default |
| Backup loss | API backup + documented restore procedure; database ignored by git |
| Rate-limit evasion | No account rotation, proxy rotation, CAPTCHA solving, or scraping; analytics imported manually |

### Residual risks

1. **Everygen live behavior is unverified.** Tool names, endpoints, credit pricing, and authentication can change. The adapter is intentionally mock-only.
2. **MCP live transport is unverified.** The registry records calls but does not speak a real transport.
3. **CUA broker does not drive a browser.** It records and scopes actions; a vetted UI driver must be attached behind the same interface.
4. **Live platform APIs are absent.** OAuth, upload quotas, disclosure rules, and platform policy reviews remain prerequisites.
5. **SQLite is not a multi-user queue.** Production needs PostgreSQL and a durable worker process.
6. **Local auth is optional and static.** `FOUNDER_TOKEN` is suitable for local use only; production requires session auth, HTTPS, and secret management.

---

## 5. MVP scope delivered

- Ten-view Founder Control Tower with live WebSocket summary.
- Seeded virtual enterprise: 1 business, 7 departments, 38 workers.
- Rights records, approvals, task DAGs, task events, audit trail.
- AI CEO plan generation, founder acceptance/rejection, task execution, retries, dead-letter handling, department/worker pause.
- Local ingest, hash, ffprobe, optional transcription, candidate scoring, five creative styles, 9:16 FFmpeg render, SRT captions, QC.
- Everygen quote/approval/mock async job lifecycle with budget and provenance.
- MCP server/tool registry with risk gates and audit records.
- CUA sessions with allowlist, observe/draft, capability tokens, action caps, expiry, evidence, emergency stop.
- Publishing accounts, jobs, approval locks, dry-run posts, reconciliation, analytics snapshots.
- Cost ledger, daily/weekly reports, style performance, JSON export, backup.
- 36 automated tests covering the critical journeys.

---

## 6. Explicit non-goals in this release

- No live Everygen API call.
- No live MCP transport.
- No browser automation.
- No live YouTube/TikTok upload.
- No platform scraping or analytics API integration.
- No multi-user authentication or role management.
- No PostgreSQL, Redis, MinIO, or container deployment.
- No claim of legal permission for any specific GTA 6 footage; the founder must attach rights evidence per asset.

---

## 7. Activation checklist before enabling external capabilities

1. Re-read the official Everygen / MCP / YouTube / TikTok documentation and record the retrieval date.
2. Implement the live adapter with a time-limited credential reference, not a static secret.
3. Add contract tests with mocked provider responses and explicit failure/idempotency cases.
4. Add a founder approval record for the target and capability.
5. Run in sandbox/dry-run mode first.
6. Verify disclosure, attribution, and platform policy requirements.
7. Raise the provider budget deliberately and monitor cost events.
8. Keep emergency stop and capability revocation tested.

**Decision:** ship the local MVP with external integrations off by default. The factory remains useful with Everygen, MCP, CUA, and live publishing disabled.
