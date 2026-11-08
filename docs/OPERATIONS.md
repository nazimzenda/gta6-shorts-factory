# Operations Guide

**Audience:** founder and future operators  
**Scope:** local single-founder deployment  
**System:** GTA 6 Shorts Factory

---

## 1. Start and stop

### Start

```bash
cd /path/to/gta_automation
source .venv/bin/activate
./launch.sh
```

Open <http://127.0.0.1:8000>. The API documentation is at `/docs`.

### Stop

Send `Ctrl+C` to the foreground process, or stop the background PID if launched with `nohup`.

### Health checks

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/health/detail
curl -s http://127.0.0.1:8000/api/system/status
```

`/health/detail` reports database integrity, emergency state, media-tool availability, and integration flags.

---

## 2. First-run setup

1. Confirm FFmpeg and ffprobe are installed:

   ```bash
   ffmpeg -version
   ffprobe -version
   ```

2. Optional: install `faster-whisper` for local transcription. Without it, attach a manual transcript or accept the explicit `unavailable` status.
3. Set a founder token if the machine is shared:

   ```bash
   export FOUNDER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
   ```

   The dashboard sends the token from `localStorage.founderToken`; the API also accepts `Authorization: Bearer <token>`.
4. Keep `EVERYGEN_ENABLED=false`, `CUA_ENABLED=false`, `PUBLISHING_ENABLED=false`, and `PUBLISHING_DRY_RUN=true` until the activation checklist is complete.

---

## 3. Daily operating procedure

### Morning

- Open **Founder Home**. Review alerts, health score, pending approvals, publishing calendar, and spend.
- Check **Departments** for paused workers or open task queues.
- Open **Department Flow** to see cross-department handoffs, the current bottleneck, and the live department bus.
- Check **Integrations** for provider/MCP health and budget.

### Production

1. **Ingest** a source in **Assets & Rights** (upload or local path).
2. **Add rights** with owner, license, platforms, commercial use, attribution, proof, and expiry.
3. Open **Approvals** and decide the rights record. Unknown or expired rights stay blocked.
4. **Analyze** the source. Review transcript status and candidate scores.
5. **Create variants** from the strongest candidate. Five styles are produced: reaction-first, story-first, funny-failure, discovery, fast-caption.
6. **Render** the selected variant. FFmpeg writes a 1080×1920 MP4 and an SRT sidecar under `data/renders` and `data/captions`.
7. **Run QC**. Inspect any failed check; do not bypass a failed rights or audio check.
8. **Submit for founder review** and approve the final video.
9. **Create a publishing job** and approve the publish decision.
10. **Publish** in dry-run mode. A simulated post is recorded, not a real platform upload.
11. **Import analytics** from a permitted export and compare style performance.

### End of day

- Clear or prioritize the approval queue.
- Check dead-letter tasks and render failures.
- Record any manual cost events.
- Create a database backup.
- Export the founder report if a weekly review is due.

---

## 4. Approval queue reference

| Approval type | What it unlocks | What it does **not** unlock |
|---|---|---|
| `rights` | Analysis, rendering, QC, publishing eligibility for that source | Provider spend or platform upload |
| `initiative_plan` | Department task queue | Any paid or external action |
| `final_video` | Publishing job creation | The publish action itself |
| `publish_final` | One publish action for that job | Future jobs or other platforms |
| `provider_quote` | One provider job for that quote | A different quote or platform |
| `cua_session` | One guarded CUA session | Publishing, payment, deletion, credential entry |
| `mcp_tool` | A high-risk tool call | Other tools or future calls |
| `script` | Script-level review state | Final video or publishing |

Decisions are append-only from the operator's perspective. An approval cannot be silently reversed after a decision; create a new record if circumstances change.

---

## 5. Worker and department controls

- **Pause department** stops its queued tasks from executing and pauses its workers.
- **Pause worker** prevents that worker from starting new tasks.
- **Retry task** resets attempts to zero and returns the task to the queue.
- **Cancel task** blocks execution; completed tasks cannot be cancelled.
- **Dead letter** means the task exhausted its retry budget. Inspect the error and evidence before retrying.
- Department and worker state is visible in **Departments**; task evidence is in the task detail or audit trail.

---

## 6. Emergency stop and incident response

### Engage

Click **EMERGENCY STOP** in the sidebar, or:

```bash
curl -X POST http://127.0.0.1:8000/api/system/emergency-stop
```

Effects:

- All mutating `/api` calls return HTTP `423` (`emergency_stop`).
- Active CUA sessions are stopped and capability tokens are cleared.
- The dashboard shows the incident state on every view.
- Reads, approvals, and the audit trail remain available.

### Respond

1. Identify the failing action in **Founder Home → Recent activity** or `GET /api/system/audit`.
2. Check failed provider jobs, render jobs, task errors, and CUA evidence under `data/evidence/`.
3. Fix the cause (rights, credentials, media file, provider budget, CUA target).
4. Resume only when safe:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/system/resume
   ```

5. Re-run the affected task or create a fresh approval.

### CUA-specific stop

```bash
curl -X POST http://127.0.0.1:8000/api/cua/emergency-stop
```

This stops CUA sessions without resuming the company-wide stop.

---

## 7. Backup and restore

### Create a backup

From the dashboard (**Founder Home** or **Analytics**) or:

```bash
curl -X POST http://127.0.0.1:8000/api/system/backup
ls -lh data/backups/
```

The SQLite online backup API is used, so the backup is consistent while the server runs.

### Restore

```bash
# 1. Stop the server.
# 2. Preserve the current database for investigation.
mv data/factory.db data/factory.db.failed

# 3. Restore.
cp data/backups/factory-<timestamp>.db data/factory.db

# 4. Remove stale WAL/SHM files if they belong to the failed database.
rm -f data/factory.db-wal data/factory.db-shm

# 5. Restart and verify.
./launch.sh
curl -s http://127.0.0.1:8000/health/detail
```

### Restore drill

Perform quarterly:

1. Create a backup.
2. Stop the server.
3. Restore into a temporary data directory (`GTA_DATA_DIR=/tmp/factory-restore`).
4. Start on a different port (`PORT=8010 ./launch.sh`).
5. Verify dashboard counts, rights records, approvals, and audit events.
6. Remove the temporary directory.

---

## 8. Cost and budget control

- Everygen quotes are stored with credits, USD estimate, expiry, and approval.
- The budget check uses recorded `cost_events` with provider `everygen`.
- A completed mock job records a `paid_generation` cost event.
- Local renders and dry-run publishing record zero-cost events for traceability.
- Add manual cost events in **Analytics & Finance** for infrastructure or other spend.
- Lower `EVERYGEN_BUDGET_USD` before enabling the provider for a pilot.

---

## 9. Enabling external capabilities later

### Everygen

1. Verify official documentation, MCP tool names, auth, pricing, and terms.
2. Implement the live adapter while keeping `EVERYGEN_MOCK=true` as the default.
3. Add contract tests with mocked responses and failure/idempotency cases.
4. Enable in a sandbox with a small budget and no publishing.
5. Require founder quote approval before every job.
6. Keep the mock fallback if the provider is unavailable.

### MCP

1. Verify the server's transport and authentication.
2. Add a scoped adapter behind `MCPRegistry`.
3. Keep high-risk tool approval mandatory.
4. Run with `MCP_LIVE_ENABLED=false` until contract tests pass.

### CUA

1. Attach a vetted browser driver in an isolated environment.
2. Keep observe mode first; test evidence capture and stop behavior.
3. Add draft mode only after the sandbox review.
4. Never enable a publish action in the CUA broker.
5. Keep allowlists, action caps, expiry, and emergency stop enabled.

### Publishing

1. Complete platform developer review and OAuth setup.
2. Store only credential references; inject secrets at runtime.
3. Implement an official API adapter with rate-limit compliance.
4. Test in an unlisted/sandbox channel.
5. Keep `PUBLISHING_DRY_RUN=true` until the founder signs off.
6. Never bypass rate limits, CAPTCHA, or platform policy.

---

## 10. Pilot checklist

- [ ] Small rights-cleared batch selected.
- [ ] Every source has an approved commercial rights record.
- [ ] Rights proof is stored and attributable.
- [ ] Every output is reviewed by the founder.
- [ ] QC passes for every submitted variant.
- [ ] No live provider spend or live publishing.
- [ ] Backups created before and after the pilot.
- [ ] Retention/quality metrics recorded from permitted exports.
- [ ] Workflow failures documented and fixed.
- [ ] Operating procedure updated with lessons.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Render returns 503 | FFmpeg/ffprobe missing | Install FFmpeg and restart |
| Analysis returns 403 `rights_blocked` | No approved commercial rights, or expired/platform mismatch | Add/approve rights or correct expiry/platforms |
| Analysis says duration unknown | ffprobe missing or unreadable media | Install ffprobe or provide a valid media file |
| Transcription `unavailable` | No local Whisper runtime | Install `faster-whisper` or attach a manual transcript |
| Everygen 403 `policy_blocked` | Provider disabled | Enable deliberately after verification |
| Provider job 403 `approval_required` | Quote not approved, or approval type/subject mismatch | Approve the quote and pass its approval id |
| Publishing 403 | Final video or publish approval missing, or QC failed | Clear both approvals and re-run QC |
| CUA 403 | Disabled, domain not allowlisted, invalid token, wrong mode, action cap, or expiry | Inspect the session and approval; never bypass the gate |
| Emergency stop 423 | Company-wide stop active | Resume after investigation |
| `Founder token required` | `FOUNDER_TOKEN` set but header absent | Set `localStorage.founderToken` or send bearer token |
| MCP 403 | Live transport disabled or high-risk approval missing | Keep registry mode or add the approval |

---

## 12. Data retention

- Keep source rights evidence for at least as long as the content is published.
- Keep audit events and approval records for the life of the business.
- Keep source, render, and caption files according to the license; delete when rights expire if required.
- Back up before schema upgrades, provider activation, and pilot runs.
- Do not commit `data/`, `.env`, credentials, or platform exports to git.
