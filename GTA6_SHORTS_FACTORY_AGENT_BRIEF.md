# GTA 6 Shorts Factory
## Founder Control Tower and AI Enterprise Specification

**Document status:** Product and engineering specification  
**Audience:** The implementation AI agent, human founder, and future contributors  
**Primary objective:** Build a local-first, rights-aware production company that discovers, edits, reviews, and publishes short-form gaming videos with human approval.

> **Important:** This document is a blueprint, not permission to copy, scrape, or mass-publish other people's content. The system must only process footage and audio that we own, have permission to use, or can legally use under a documented license. Every publishing action requires a human approval gate.

---

## 1. Vision

The founder owns a virtual media enterprise. The founder gives strategic instructions to an AI CEO. The AI CEO coordinates departments, managers, and workers. Each worker has a role, illustrated identity, queue of assignments, status, evidence, and performance metrics.

The first business is a **GTA 6 creator-clips factory**:

1. Find rights-cleared source footage or founder-provided recordings.
2. Detect promising moments such as reactions, funny failures, discoveries, or dramatic gameplay.
3. Transcribe and score candidate moments.
4. Produce several original vertical-short variations.
5. Add captions, attribution, commentary, branding, and accessibility metadata.
6. Send every candidate to the founder for review.
7. Publish approved videos to supported channels.
8. Track performance, rights, costs, and lessons.

The platform must later support other games, streamers, projects, and businesses without rewriting the core system.

## 2. Business and ethical boundary

The system is intended to create sustainable, original media—not to exploit creators or platform loopholes.

### Required rights policy

For every source asset, store:

- owner or creator;
- source URL and retrieval date;
- permission or license record;
- allowed platforms;
- commercial-use status;
- attribution requirements;
- expiry date, if any;
- proof file or written agreement;
- takedown contact and review status.

Do not process an asset when rights are unknown. Do not remove watermarks, disguise a source, impersonate a creator, or claim another person's video as our own.

Rockstar's current policies, game release information, and platform rules must be verified from official sources at implementation time. The agent must not assume that fan-content tolerance equals commercial permission. YouTube and TikTok rules can change; implement a policy adapter and re-check before launch.

## 3. Product principles

1. **Founder remains the final authority.**
2. **AI proposes; humans approve consequential actions.**
3. **MCP first for structured integrations.**
4. **CUA only for permitted, visible, auditable UI workflows.**
5. **Local-first processing to reduce recurring API cost and vendor lock-in.**
6. **Every action is logged and reproducible.**
7. **No silent fallbacks, hidden spending, or automatic publishing.**
8. **Quality and originality are more important than volume.**
9. **One platform's rate limit or terms must never be bypassed.**
10. **Everygen.ai is optional infrastructure, not a hard dependency.**

## 4. Virtual enterprise model

### Founder

The founder is the only required human operator. The founder can:

- define strategy and brand rules;
- approve or reject source rights;
- approve budgets and paid generation quotes;
- approve final videos;
- approve publishing;
- pause any department or worker;
- revoke credentials and CUA sessions;
- review company reports.

The founder should communicate primarily with the AI CEO rather than manually managing every worker.

### AI CEO

The CEO converts founder goals into initiatives, assigns work, resolves conflicts, requests approvals, and reports:

- current objectives;
- blockers;
- production throughput;
- quality and originality scores;
- publishing status;
- revenue and cost estimates;
- policy or rights risks.

The CEO may not approve its own high-risk actions. It must route them to the Founder Approval Queue.

### Departments and example workers

#### Research and Rights Department

- Trend Researcher
- Game News Researcher
- Creator Partnership Researcher
- Rights and Licensing Officer
- Source Verification Worker

#### Creative Department

- Format Strategist
- Hook Writer
- Script Writer
- Thumbnail and Cover Designer
- Brand Guardian

#### Production Department

- Ingest Worker
- Scene Detection Worker
- Highlight Scout
- Transcription Worker
- Caption Designer
- Vertical Editor
- Audio Mixer
- Quality-Control Worker

#### Publishing Department

- Metadata Writer
- Platform Policy Checker
- YouTube Publisher
- TikTok Publisher
- Schedule Coordinator

#### Analytics Department

- Performance Analyst
- A/B Test Analyst
- Retention Analyst
- Experiment Planner

#### Engineering and Automation Department

- Pipeline Engineer
- MCP Integration Engineer
- CUA/Desktop Automation Engineer
- Infrastructure Engineer
- Security and Secrets Engineer
- Test Engineer

#### Operations and Finance Department

- Queue Manager
- Cost Controller
- Asset Librarian
- Backup Worker
- Incident Coordinator

Every worker must have a clear input, output, permission scope, retry policy, and evidence record.

## 5. Founder Control Tower dashboard

The dashboard is the command center for all present and future businesses.

### Required views

1. **Founder Home**
   - company health;
   - active initiatives;
   - approvals requiring attention;
   - recent worker activity;
   - cost and quota summary;
   - publishing calendar.

2. **AI CEO Office**
   - send a strategic instruction;
   - view CEO plan;
   - accept, reject, or edit the plan;
   - view escalations and blockers.

3. **Departments**
   - illustrated department cards;
   - managers and workers;
   - queues, assignments, SLAs, and status;
   - pause/resume controls;
   - worker permissions.

4. **Projects and Businesses**
   - GTA 6 Clips;
   - additional games;
   - creator partnerships;
   - future businesses;
   - shared assets and isolated workspaces.

5. **Production Board**
   - Kanban stages: intake, rights review, ingesting, analyzing, editing, QC, founder review, approved, scheduled, published, rejected, archived;
   - candidate scores;
   - previews and source references;
   - batch and single-item actions.

6. **Founder Approval Queue**
   - rights approval;
   - paid Everygen quote approval;
   - generated script approval;
   - final video approval;
   - publishing approval;
   - CUA session approval.

7. **Assets and Rights**
   - original media;
   - derived clips;
   - captions and transcripts;
   - licenses and permissions;
   - takedown and expiry warnings.

8. **MCP and Integrations**
   - connected MCP servers;
   - tool schemas;
   - scopes;
   - health;
   - last use;
   - failures;
   - revoke button.

9. **CUA Sessions**
   - active session;
   - target application;
   - screenshot/evidence trail;
   - actions taken;
   - allowed domains;
   - approval status;
   - pause and revoke controls.

10. **Analytics and Finance**
    - views, retention, likes, comments, follows;
    - per-video and per-batch cost;
    - provider credits;
    - revenue estimates;
    - experiments;
    - exportable reports.

### Illustrated enterprise UX

Use illustrated avatars as an interface metaphor, not as evidence that an autonomous person exists. Each avatar must open the real worker's:

- current assignment;
- input and output;
- status;
- last action;
- evidence;
- error;
- required approval;
- cost.

## 6. Recommended architecture

```text
Founder Dashboard
        |
AI CEO / Orchestrator
        |
Task Queue + Approval Service + Policy Engine
        |
-----------------------------------------------------
| Research | Rights | Production | Publishing | Data |
-----------------------------------------------------
        |
MCP Gateway ---- Everygen.ai (optional remote provider)
        |
Local Services: FFmpeg, Whisper, OCR, local LLM, storage
        |
Optional CUA Broker (isolated desktop automation)
```

### Proposed local stack

Choose stable, well-maintained open-source components and verify licenses before adopting:

- **Backend:** Python with FastAPI, or TypeScript with a typed API layer.
- **Database:** PostgreSQL in production; SQLite is acceptable for the first local prototype.
- **Queue:** Redis plus a durable job worker, or a PostgreSQL-backed queue.
- **Object storage:** MinIO locally, with an S3-compatible abstraction.
- **Media:** FFmpeg and ffprobe.
- **Video composition:** Remotion, MoviePy, or FFmpeg filter graphs.
- **Speech-to-text:** Whisper or faster-whisper, running locally when hardware permits.
- **OCR:** Tesseract or PaddleOCR.
- **Local models:** Ollama, llama.cpp, or another documented local runtime.
- **Embeddings/search:** PostgreSQL pgvector or a local vector store.
- **Frontend:** React/Next.js or another typed dashboard framework.
- **Observability:** structured JSON logs, OpenTelemetry-compatible traces, and a local metrics view.
- **Authentication:** local account initially; production deployment must use strong authentication, encrypted secrets, and least privilege.

Do not add a dependency merely because it is popular. Record license, maintenance status, hardware requirements, and fallback behavior for each chosen tool.

## 7. MCP versus CUA: the correct decision

### MCP is the primary integration layer

Use MCP when the target service exposes structured tools or a documented API. MCP provides:

- discoverable tool schemas;
- typed inputs and outputs;
- permission boundaries;
- easier logging and testing;
- fewer fragile UI assumptions.

The agent should use MCP for the orchestration layer, local media tools, storage, metadata, analytics, and Everygen.ai when connected.

### CUA is a controlled fallback

Use CUA only when:

- no suitable API or MCP tool exists;
- the workflow is explicitly allowed by the service;
- the founder has approved the target and action;
- the session runs in an isolated browser or desktop;
- all actions and screenshots are logged;
- the workflow has a dry-run mode;
- the agent can stop safely on unexpected UI changes.

CUA must not:

- evade CAPTCHA, authentication controls, or platform enforcement;
- bypass rate limits;
- create fake accounts;
- mass-like, mass-follow, or spam;
- publish without the Founder Approval Queue;
- handle unrestricted credentials;
- conceal automation from a service that prohibits it.

### CUA broker design

Create a local broker with:

- explicit allowlisted domains and applications;
- per-session capability tokens;
- read-only mode by default;
- separate `observe`, `draft`, and `publish` capabilities;
- maximum action count and time limit;
- screenshot and action log;
- emergency stop;
- human confirmation for login, payment, deletion, and publishing;
- encrypted secret injection without exposing secrets to the model.

Candidate open-source CUA implementations may be evaluated, including Open Computer Use, OpenAdapt, or UI-TARS Desktop. The implementation agent must inspect current repositories, license terms, maintenance, and security before selecting one. CUA is replaceable; the broker interface must not depend on one vendor.

## 8. Everygen.ai integration

Everygen.ai should be integrated as an **optional remote creative provider behind an adapter**.

Based on the provider information available during specification writing, Everygen.ai is described as an MCP-connected service for media generation and creative workflows, with asynchronous jobs, account credits, and approval-aware generation. The implementation agent must verify the live official documentation before coding because endpoints, tool names, authentication, pricing, and capabilities can change.

Reference links to verify:

- Everygen site: <https://everygen-ai.com>
- Everygen MCP repository: <https://github.com/bytevirts/everygen-mcp>

Do not hard-code unverified tool names, endpoint behavior, or a claim that the service is free.

### Provider adapter contract

Implement a provider interface similar to:

```text
get_capabilities() -> Capabilities
estimate_cost(request) -> Quote
create_image(request, approved_quote_id) -> Job
create_video(request, approved_quote_id) -> Job
create_voice(request, approved_quote_id) -> Job
get_job(job_id) -> JobStatus
download_result(job_id) -> Asset
cancel_job(job_id) -> CancellationResult
```

The adapter must:

- use the provider's official authentication flow;
- never store a static token in source code;
- show quote, credits, and expected output before paid execution;
- require a founder approval ID for paid generation;
- persist provider job IDs and raw status safely;
- support retries only when idempotency is known;
- handle asynchronous completion and failure explicitly;
- record provenance and provider terms for each generated asset;
- allow disabling Everygen without breaking local production.

### Everygen workflow

1. Creative worker drafts a generation request.
2. Policy worker checks prompt, rights, and brand rules.
3. Cost controller requests a quote.
4. Dashboard displays provider, estimated credits, limits, and alternatives.
5. Founder approves or rejects.
6. Adapter submits through MCP or the documented official integration.
7. Worker polls or receives completion according to provider documentation.
8. Result is stored with provenance and license metadata.
9. Human reviews before publication.

Everygen-generated visuals, narration, music, or video must be labeled internally as AI-generated. Platform disclosure requirements must be checked before publishing.

## 9. Local-first API-limit strategy

The goal is to reduce unnecessary external calls, not to circumvent limits.

### Use local processing for

- downloading founder-owned or licensed files;
- scene detection;
- silence detection;
- transcription;
- caption timing;
- resizing and rendering;
- audio normalization;
- duplicate detection;
- metadata drafts;
- quality checks;
- analytics aggregation from permitted exports.

### Responsible external-call policy

- cache results using content hashes;
- deduplicate identical requests;
- use exponential backoff with jitter;
- honor `Retry-After`;
- enforce per-provider budgets;
- use official batch or export mechanisms;
- keep a local queue;
- pause on repeated errors;
- surface limits in the dashboard;
- never rotate accounts, proxies, or identities to evade restrictions.

## 10. Production pipeline

### Stage A: Intake

- accept local files or documented permitted sources;
- calculate hash and technical metadata;
- create an asset record;
- attach rights evidence;
- reject unknown or expired rights.

### Stage B: Analysis

- extract audio and video metadata;
- transcribe locally;
- detect scenes, faces, speech, laughter, silence, and high-energy moments;
- identify potential hooks;
- generate a candidate timeline with confidence and explanation.

### Stage C: Creative package

For each candidate, create 3-5 materially different drafts, for example:

- reaction-first;
- story-first;
- funny-failure;
- discovery/explanation;
- fast caption-led cut.

Differences must be meaningful: hook, pacing, commentary, captions, or structure—not tiny duplicate variations.

### Stage D: Edit

Default target:

- 9:16 vertical;
- 1080x1920 when source and hardware allow;
- readable captions with safe margins;
- clear audio;
- no clipped speech;
- original branding;
- source attribution where required;
- no deceptive title or thumbnail.

### Stage E: Quality control

Automated checks:

- file decodes;
- duration is within configured range;
- audio is present and not distorted;
- captions fit safe areas;
- no accidental private data;
- rights record is valid;
- duplicate/perceptual similarity is within policy;
- metadata is complete.

Human checks:

- factual accuracy;
- originality and transformation;
- respectful treatment of creators;
- correct attribution;
- platform suitability;
- final title, description, hashtags, and disclosure.

### Stage F: Approval and publishing

No automatic publication from an unreviewed worker. The founder approves:

1. source rights;
2. final video;
3. platform and schedule;
4. any paid generation or promotion.

Publishing workers only operate with short-lived, least-privilege credentials and a specific approval ID.

## 11. Data model

At minimum implement:

- `businesses`
- `departments`
- `workers`
- `initiatives`
- `tasks`
- `task_events`
- `approvals`
- `media_assets`
- `source_assets`
- `rights_records`
- `transcripts`
- `highlight_candidates`
- `video_variants`
- `render_jobs`
- `provider_accounts`
- `provider_quotes`
- `provider_jobs`
- `mcp_servers`
- `mcp_tool_calls`
- `cua_sessions`
- `cua_actions`
- `publishing_accounts`
- `publishing_jobs`
- `platform_posts`
- `analytics_snapshots`
- `cost_events`
- `audit_events`

Every important record should include stable ID, timestamps, status, owner worker, provenance, and audit references.

## 12. Permission model

Use capability-based permissions:

- `read_assets`
- `create_drafts`
- `render_video`
- `request_provider_quote`
- `execute_paid_generation`
- `manage_rights`
- `manage_credentials`
- `publish_draft`
- `publish_final`
- `run_cua_observe`
- `run_cua_draft`
- `run_cua_publish`

Default permissions must be minimal. `execute_paid_generation`, `manage_credentials`, and `publish_final` always require founder approval.

## 13. Implementation phases

### Phase 0 — Audit and decisions

- inspect hardware, operating system, available storage, GPU, and installed runtimes;
- inspect current official Everygen.ai documentation;
- inspect candidate MCP and CUA projects;
- record licenses and risks;
- choose initial stack;
- produce an implementation plan for founder review.

### Phase 1 — Foundation

- create repository structure;
- add configuration and secret handling;
- add database migrations;
- add structured logging and audit events;
- add health checks;
- add tests and local development instructions.

### Phase 2 — Founder Control Tower

- implement authentication;
- build dashboard shell;
- implement companies, departments, workers, tasks, approvals, and audit timeline;
- add illustrated worker cards;
- add pause, revoke, and emergency-stop controls.

### Phase 3 — Local media factory

- implement ingest;
- add FFmpeg/ffprobe;
- add transcription;
- add candidate detection;
- add captioning and vertical rendering;
- add QC;
- add preview playback.

### Phase 4 — AI enterprise orchestration

- implement CEO planning;
- add department queues;
- add worker execution;
- add retry and escalation policy;
- add evidence and report generation.

### Phase 5 — MCP gateway and Everygen adapter

- implement MCP registry and permission layer;
- connect Everygen only after official verification;
- implement quote-before-spend;
- implement asynchronous job tracking;
- add provider fallback to local tools;
- add integration tests with mocked provider responses.

### Phase 6 — CUA broker

- start with observe-only sessions;
- add isolated browser/desktop;
- implement allowlists, evidence, timeouts, and emergency stop;
- test with a non-publishing sandbox;
- add draft-only workflows;
- enable publishing only after explicit founder approval and policy review.

### Phase 7 — Publishing and analytics

- integrate official platform APIs where available;
- use CUA only where permitted and unavoidable;
- add scheduling;
- add post IDs and status reconciliation;
- import analytics;
- build experiments and reports.

### Phase 8 — Pilot

- process a small rights-cleared batch;
- review every output;
- publish a limited number;
- measure quality and retention;
- fix workflow failures;
- document a repeatable operating procedure.

## 14. Definition of done

The first release is complete only when:

- founder can see all departments and assignments;
- every worker produces auditable evidence;
- no unknown-rights asset can enter rendering;
- every paid provider action has a quote and approval;
- local rendering works without Everygen;
- Everygen can be disabled through configuration;
- CUA has isolation, allowlists, logs, timeout, and emergency stop;
- publishing cannot happen without final founder approval;
- failures are visible and actionable;
- tests cover rights gates, approvals, idempotency, provider failures, and publishing locks;
- backup and restore are documented;
- the founder can stop all work from one screen.

## 15. Initial founder instruction to the implementation agent

Use this as the first command to the implementation agent:

> You are the AI Chief Technology Officer reporting to the Founder. Build the GTA 6 Shorts Factory according to this specification. Start with Phase 0 only. Audit the computer, available runtimes, storage, GPU, local models, candidate MCP integrations, Everygen.ai's current official documentation, and candidate CUA implementations. Do not spend money, connect accounts, publish content, or modify external services. Return a decision report containing the proposed stack, license checks, security risks, hardware assumptions, MVP scope, and implementation plan. Wait for Founder approval before proceeding.

## 16. Operating instructions for the AI CEO

The CEO must:

- ask for a strategic objective when none exists;
- decompose objectives into department tasks;
- assign only workers with required permissions;
- show cost and risk before external execution;
- escalate rights ambiguity;
- stop on policy conflicts;
- avoid duplicate work using asset and task hashes;
- report failures rather than hiding them;
- keep the founder's approval queue short and prioritized;
- produce a daily summary and a weekly business report.

## 17. Success metrics

Track:

- approved assets per week;
- candidate-to-approved ratio;
- average editing time;
- render failure rate;
- caption correction rate;
- rights-review completion rate;
- percentage processed locally;
- external credits consumed;
- cost per approved video;
- founder approval time;
- publishing error rate;
- average view duration;
- retention curve;
- follows per thousand views;
- takedown or complaint count;
- revenue only after it is actually verified.

Do not optimize for uploads alone. Optimize for legal safety, originality, viewer value, quality, and repeatable economics.

## 18. Final strategy

The best design is not “Everygen versus MCP versus CUA.”

- **MCP is the control plane** for typed, inspectable tools.
- **Local open-source tools are the production engine** for routine media work.
- **Everygen.ai is an optional creative provider** for capabilities that are worth its credits.
- **CUA is a guarded compatibility layer** for permitted UI-only workflows.
- **The Founder Control Tower is the source of truth** for people, work, approvals, costs, and evidence.

Build the system so that it remains useful if Everygen changes pricing, becomes unavailable, or is removed. Build it so that automation creates genuinely transformed, rights-cleared content rather than a high-volume reposting machine. The founder should have one dashboard, one approval queue, and one reliable audit trail.

---

## Sources to verify before implementation

- Everygen official site: <https://everygen-ai.com>
- Everygen MCP repository: <https://github.com/bytevirts/everygen-mcp>
- Open Computer Use candidate: <https://github.com/iFurySt/open-computer-use>
- OpenAdapt candidate: <https://github.com/OpenAdaptAI/OpenAdapt>
- Model Context Protocol: <https://modelcontextprotocol.io>
- YouTube policies and developer documentation: <https://support.google.com/youtube>
- TikTok developer documentation: <https://developers.tiktok.com>
- Rockstar Games official site and support policies: <https://www.rockstargames.com> and <https://support.rockstargames.com>

All sources, endpoints, prices, permissions, and policies must be re-checked at implementation time.
