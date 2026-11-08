# GTA 6 Shorts Factory

**Local-first Founder Control Tower for rights-cleared short-form video production.**

The factory discovers, edits, reviews, and prepares short-form gaming videos with a human founder as the final authority. The **Founder Control Tower itself is intentionally not an auto-posting farm**: unknown rights are blocked, paid provider calls are quote-gated, its CUA broker is observe/draft only, and its publishing adapter is dry-run by default. A separate **CUA Shorts Pipeline** (documented below) can operate the owner's signed-in browser sessions end to end; it uses no API keys, is dry-run by default, and requires an explicit `--live` to publish.

---

## What is implemented

The whole local MVP is implemented across the original eight phases:

| Area | Status | Notes |
|---|---|---|
| Founder Control Tower | Complete | Eleven views: Home, CEO Office, Departments, Department Flow, Projects, Production Board, Approvals, Assets & Rights, Integrations, CUA, Analytics & Finance |
| Enterprise model | Complete | Business, departments, 38 seeded workers, queues, task DAGs, department interaction map, pause/resume, dead-letter handling |
| Rights gate | Complete | Owner, license, platforms, commercial use, attribution, expiry, proof, founder approval |
| Local media pipeline | Complete | Hash, ffprobe metadata, optional Whisper transcription, candidate scoring, 5 creative variants, 9:16 render, SRT captions, QC |
| AI CEO orchestration | Complete | Objective → 12-task plan → founder acceptance → department execution with evidence |
| MCP gateway | Complete (registry) | Server/tool registry, risk scopes, hashed call records; live transport intentionally disabled |
| Everygen adapter | Complete (mock) | Capabilities, quotes, budget, approval gate, async job lifecycle, provenance; no network calls |
| CUA broker | Complete (guarded) | Allowlist, observe/draft modes, capability tokens, action limits, expiry, evidence files, emergency stop |
| CUA shorts pipeline | Complete (operator tool) | YouTube discovery → Everygen → download → YouTube/TikTok browser publishing, no API keys, dry-run default |
| Free clip mode | Complete (operator tool) | `yt-dlp` YouTube source → caption/Whisper highlight selection → FFmpeg 1080×1920 clips with subtitles → dashboard multi-source form → same CUA publisher, no credits/watermark |
| Publishing | Complete (dry-run) | Final-video + publish approvals, scheduling records, simulated posts, reconciliation, analytics |
| Analytics & finance | Complete | Views/retention/follows, QC pass rate, cost ledger, daily/weekly reports, style comparison |
| Audit & recovery | Complete | Append-only audit events, task events, database backup, emergency stop |

All external integrations are feature-flagged **off** by default. Local production works with Everygen, MCP, CUA, and live publishing disabled.

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Local media tools (required for rendering and QC)
ffmpeg -version
ffprobe -version

./launch.sh
```

Open <http://127.0.0.1:8000>. The FastAPI docs are at `/docs` and health is at `/health`.

The first launch seeds the business, seven departments, and 38 workers. No approvals, assets, spends, CUA sessions, or posts are created automatically.

Run the test suite:

```bash
.venv/bin/pytest -q
```

---

## The operating workflow

1. **Ingest** a founder-owned or licensed source in **Assets & Rights**.
2. **Add a rights record** and approve it in the **Approval Queue**.
3. **Analyze** the source. The pipeline hashes it, probes it, optionally transcribes locally, and proposes highlight candidates.
4. **Create variants** — five materially different creative directions per candidate.
5. **Render** 9:16 locally with FFmpeg and generate a sidecar SRT caption file.
6. **Run QC** — decode, duration, 1080×1920, audio, captions, rights, file size.
7. **Submit for founder review** and approve the final video.
8. **Create a publishing job**, approve the publish decision, and run the dry-run publish.
9. **Import analytics snapshots** from permitted platform exports.
10. **Review the daily/weekly report**, costs, and style performance.

Any paid provider or CUA action follows the same approval pattern.

### CUA Shorts Pipeline (no API keys)

A separate CUA pipeline automates the full loop requested for this project:

```text
YouTube public search → GTA 6 links → Everygen Shorts Studio (GTA 6 format)
→ download MP4 → YouTube Shorts + TikTok
```

It drives the owner's already signed-in Firefox sessions inside the same Cua VM
used by `v2-automation`. It uses **no Everygen, YouTube or TikTok API key** and
never stores a password. The control tower remains approval-gated; the pipeline
is a separate operator tool with its own database, evidence and logs.

```bash
source .venv/bin/activate
python -m pipeline.run prepare       # start/recover the CUA VM
python -m pipeline.run open-logins   # sign in once: YouTube, TikTok, Everygen
python -m pipeline.run accounts      # verify the sessions
python -m pipeline.run cycle         # dry run
python -m pipeline.run cycle --live  # real publish
python -m pipeline.run worker --live --interval 3600   # repeat
```

### Free clip mode (no Everygen, no credits)

The project also includes a **local YouTube clipper** for the case where you
only want to cut highlights from a YouTube link, not generate new AI footage.
It uses `yt-dlp` for the source, the video's own captions for highlight
selection, and FFmpeg for a 1080×1920 vertical clip. No provider, no credits,
no watermark.

```bash
python -m pipeline.run clip \
  --url "https://www.youtube.com/watch?v=..." \
  --count 2 --rights-ack

# full loop with clip mode
python -m pipeline.run cycle --mode clip --rights-ack --live
```

`PIPELINE_MODE=clip` is the default in this checkout. The default **streamer
layout** fills the full 1080×1920 frame from the core video, keeps the
streamer's facecam in a clean top-right PiP, and puts bold captions in the
bottom safe area. The output has **no provider watermark**. Subtitles are
burned in when available (YouTube captions first, then a local Whisper
fallback) and common typos such as `Viciti` → `Vice City` are corrected. Set
`PIPELINE_CLIP_SHOW_CAPTIONS=false` for a clean video with no subtitles. Clip
mode requires an explicit rights acknowledgement: only clip videos you own or
have permission to reuse. The dashboard's **Shorts Pipeline** tab also has an
**Add YouTube sources** form for multiple links, a clip showcase and per-clip
Play links. See [docs/CLIP_MODE.md](./docs/CLIP_MODE.md).

Dry-run is the default. Live publishing requires `--live` (or
`PIPELINE_LIVE=true`) and enforces per-platform daily caps. If the control
tower emergency stop is active, the pipeline refuses to start. Everygen
requires an active account plan or credits; if the account is signed in but has
no plan, the guest returns `PLAN_REQUIRED` and the link is kept queued for a
retry after checkout. See [docs/CUA_PIPELINE.md](./docs/CUA_PIPELINE.md) for the
full runbook, configuration, evidence layout, troubleshooting and
platform-policy notes.

### AI CEO workflow

Open **AI CEO Office**, enter a strategic objective, and deploy the plan. The CEO creates a 12-step initiative with dependencies across Research, Creative, Production, Publishing, Analytics, Engineering, and Operations. The plan sits in `plan_pending` until the founder accepts it. Accepting queues department tasks; rejecting cancels them.

Tasks without a real `input_ref` produce simulated department evidence. Tasks with `input_ref` connect to the actual local pipeline (asset id, candidate id, variant id). The CEO never approves its own high-risk work.

---

## Safety model

| Gate | Enforcement |
|---|---|
| Rights | `valid_rights()` blocks analysis, render, QC, and publishing without an approved commercial rights record that is not expired and covers the platform |
| Paid generation | Everygen is disabled by default; quotes create an approval; jobs require the approved quote; budget is checked before job creation and charging |
| Publishing | Requires both an approved `final_video` record and an approved `publish_final` record; dry-run never contacts a platform |
| CUA broker | Disabled by default; allowlisted domains; per-session capability token hash; observe/draft only; action caps; expiry; evidence files; emergency stop |
| CUA pipeline | Separate operator tool; no API keys; uses the owner's signed-in VM sessions; dry-run default; daily publish caps; screenshots/HTML evidence; refuses to run during the control-tower emergency stop |
| MCP | Registry and scoped calls; high-risk tools require an `mcp_tool` approval; live transport disabled |
| Emergency stop | Blocks all mutating `/api` calls with HTTP 423, stops CUA sessions, and is visible on every dashboard view |
| Audit | Approvals, rights, assets, renders, jobs, CUA actions, costs, reports, and emergency events are appended to `audit_events` |

The only human operator is the founder. The AI CEO cannot approve paid generation, credentials, final videos, or publishing.

---

## Configuration

Copy `.env.example` to `.env` or export variables before launching.

Important flags:

| Variable | Default | Meaning |
|---|---|---|
| `LOCAL_PROCESSING_ENABLED` | `true` | Local media pipeline |
| `EVERYGEN_ENABLED` | `false` | Enable Everygen quote adapter |
| `EVERYGEN_MOCK` | `true` | Mock async jobs; never call the provider |
| `EVERYGEN_BUDGET_USD` | `25` | Provider budget ceiling |
| `CUA_ENABLED` | `false` | Enable guarded CUA sessions |
| `CUA_ALLOWED_DOMAINS` | allowlist | Comma-separated CUA domains |
| `PUBLISHING_ENABLED` | `false` | Live publishing flag (no live adapter shipped) |
| `PUBLISHING_DRY_RUN` | `true` | Create simulated posts |
| `MCP_LIVE_ENABLED` | `false` | Live MCP transport (not implemented) |
| `FOUNDER_TOKEN` | empty | Optional bearer token for `/api` |
| `GTA_DATA_DIR` | `data` | Database, uploads, renders, evidence, exports |
| `PIPELINE_LIVE` | `false` | Autonomous CUA pipeline: click the final Publish/Post button |
| `EVERYGEN_CREDIT_BUDGET` | `200` | Daily Everygen credit ceiling (`0` = provider limit only) |
| `PIPELINE_DAILY_LIMIT_YOUTUBE` | `3` | Live YouTube posts per UTC day |
| `PIPELINE_DAILY_LIMIT_TIKTOK` | `3` | Live TikTok posts per UTC day |

### Media dependencies

- **FFmpeg + ffprobe** are required for rendering and QC. Ingest and analysis still work without them, but rendering is blocked with an explicit error.
- **yt-dlp** is required for free clip mode (download a YouTube source). It is installed by the project dependency set.
- **Whisper / faster-whisper** is optional. If installed, analysis transcribes locally. Otherwise attach a manual transcript in the Assets view or via `POST /api/assets/{id}/transcript`.
- **SQLite** is the first local system of record. The schema is migration-aware for the original foundation database.

---

## API map

| Area | Endpoints |
|---|---|
| System | `GET /health`, `GET /health/detail`, `GET /api/system/status`, `POST /api/system/emergency-stop`, `POST /api/system/resume`, `POST /api/system/backup`, `GET /api/system/backups` |
| Dashboard | `GET /api/dashboard/summary`, `GET /api/dashboard/activity`, `WS /ws/dashboard` |
| Enterprise | `/api/businesses`, `/api/departments`, `/api/departments/interactions`, `/api/workers`, `/api/tasks`, `/api/initiatives`, `/api/approvals` |
| CEO | `POST /api/ceo/instructions`, `POST /api/ceo/tick`, `GET /api/ceo/report`, `POST /api/initiatives/{id}/decision` |
| Media | `POST /api/assets/upload`, `POST /api/assets/ingest`, `POST /api/assets/{id}/analyze`, `/api/rights`, `/api/candidates`, `/api/variants`, `/api/variants/{id}/render`, `/qc`, `/submit-review` |
| Providers | `GET /api/providers`, `/api/providers/everygen/capabilities`, `/quotes`, `/jobs`, `/jobs/{id}/poll`, `/cancel` |
| MCP | `/api/mcp/servers`, `/api/mcp/tools`, `/api/mcp/tool-calls`, `/api/mcp/servers/{id}/connect` |
| CUA | `/api/cua/sessions`, `/activate`, `/actions`, `/stop`, `/api/cua/emergency-stop` |
| Publishing | `/api/publishing/accounts`, `/api/publishing/jobs`, `/publish`, `/reconcile`, `/api/publishing/posts` |
| Analytics | `GET /api/analytics/summary`, `/api/analytics/snapshots`, `/api/analytics/costs`, `/api/reports/daily`, `/api/reports/weekly`, `POST /api/reports/export` |

Full schemas are available at `/docs`.

---

## Data and backup

Runtime data lives under `data/` (ignored by git):

```text
data/
  factory.db          # SQLite system of record
  uploads/            # uploaded source files
  renders/            # 9:16 rendered variants
  captions/           # SRT files
  evidence/           # CUA action evidence
  provider_results/   # mock provider manifests
  backups/            # API-created database backups
  exports/            # founder report exports
```

Create a backup from the dashboard or API:

```bash
curl -X POST http://127.0.0.1:8000/api/system/backup
```

Restore procedure:

```bash
# Stop the server first.
cp data/backups/factory-<timestamp>.db data/factory.db
# Remove stale WAL/SHM files if present, then restart.
```

See [docs/OPERATIONS.md](./docs/OPERATIONS.md) for the full operating procedure.

---

## Limitations and next steps

- **Everygen live adapter is not implemented.** The official MCP contract, endpoints, pricing, and authentication must be verified before enabling network calls. Mock mode is deliberate.
- **MCP live transport is not implemented.** The registry and audit boundary are ready; a verified server adapter must be added with explicit scopes.
- **The CUA broker is a broker/evidence layer, not a browser driver.** The separate `pipeline` package is the browser driver: it operates the owner's signed-in Cua VM through deployed guest scripts, serialized with a file lock and backed by screenshots/HTML evidence.
- **Live platform publishing in the control tower is not implemented.** The control tower's `PUBLISHING_DRY_RUN` path still simulates posts. The separate CUA pipeline can publish through the logged-in YouTube Studio and TikTok Studio browser sessions; it defaults to dry-run and requires `--live`.
- **Analytics are imported, not scraped.** Use official exports or APIs; no platform scraping or rate-limit bypass exists.
- **Single-founder local auth only.** Production deployment needs strong authentication, HTTPS, secret management, and least-privilege service accounts.
- **SQLite concurrency is intentionally simple.** Migrate to PostgreSQL and a durable queue before multi-user or high-volume operation.

These are explicit, visible boundaries, not silent fallbacks.

---

## Documentation

- [Agent brief](./GTA6_SHORTS_FACTORY_AGENT_BRIEF.md) — product and ethics specification
- [Enterprise OS charter](./docs/ENTERPRISE_OS_CHARTER.md) — operating protocol for the Founder/COO simulation
- [Phase 0 decision report](./docs/DECISION_REPORT.md) — stack, licenses, risks, hardware assumptions
- [CUA shorts pipeline](./docs/CUA_PIPELINE.md) — no-key discovery → Everygen → YouTube/TikTok runbook
- [Free clip mode](./docs/CLIP_MODE.md) — YouTube link → caption-driven vertical highlights with FFmpeg
- [Final project status](./docs/FINAL_STATUS.md) — verification matrix and the Everygen plan notes
- [Operations guide](./docs/OPERATIONS.md) — daily runbook, approvals, backup/restore, incident response
- [Architecture diagram](./.github/modernize/assessment/engines/facts/architecture-diagram.md)

---

## Test coverage

`pytest` covers:

- health, dashboard defaults, seeded enterprise, WebSocket live feed
- department interaction map derived from cross-department task dependencies and live handoffs
- approval lifecycle and immutable decisions
- rights gate, expired rights, duplicate ingest, uploads
- full local media pipeline: ingest → analysis → 5 variants → render → SRT → QC → final approval → dry-run publish → analytics
- render reuse and QC failure paths
- CEO planning, plan acceptance/rejection, task execution, retries, department pause
- Everygen quote/budget/approval/idempotency/mock lifecycle
- MCP registry, high-risk approval, call records
- CUA allowlist, activation approval, tokens, mode limits, action caps, emergency stop
- publishing locks, QC gate, idempotency, dry-run posts, reconciliation
- optional founder token, backups, report exports, audit ordering, schema integrity
