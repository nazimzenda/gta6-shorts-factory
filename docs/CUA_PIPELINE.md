# CUA Shorts Pipeline

**Discover GTA 6 YouTube links → generate original shorts in Everygen → download → publish to YouTube Shorts and TikTok — with no platform API keys.**

The pipeline drives the owner's already signed-in browser sessions inside the
Cua VM. It never asks for a password, never stores a credential, and never uses
an Everygen, YouTube or TikTok API key. The only "key" is the live CUA session
you create by signing in once in the VM.

> The Founder Control Tower (`./launch.sh`) is still the approval-gated
> control plane. This pipeline is a separate operator tool with its own SQLite
> database, guest scripts and logs. It does not bypass the control tower's
> emergency stop: if `factory.db` has `emergency_stop = true`, every cycle
> refuses to start.

---

## 1. Architecture

```text
host                                      Cua VM (owner's signed-in sessions)
────────────────────────────────────      ────────────────────────────────────
pipeline/yt_search.py                     Firefox profile
  public YouTube search (no API key)        ├─ studio.youtube.com  (YouTube)
        │                                   ├─ tiktok.com         (TikTok)
        ▼                                   └─ everygen.ai        (Everygen)
PipelineDB (data/pipeline/pipeline.db)
        │
        ├─► guest_everygen.py  ──────────► Shorts Studio → GTA 6 format
        │                                  prompt: source link + title + direction
        │                                  wait for completion → download MP4
        │      ◄──── cua sb cp ─────────── /home/cua/Downloads/everygen
        │
        ├─► upload_yt.py       ──────────► YouTube Studio upload wizard
        │                                  dry-run: stops at review screen
        │                                  live: sets PUBLIC + clicks Publish
        │
        └─► upload_tiktok.py   ──────────► TikTok Studio upload page
                                           dry-run: stops before Post
                                           live: clicks Post + confirms
```

Everything long-running is spawned detached on the guest and short-polled by
the host (`cua sb exec` has a ~2 minute transport cap). Each stage writes a JSON
result, an exit file, a screenshot and page HTML. Evidence is copied back under
`data/pipeline/evidence/`.

---

## 2. One-time preparation

The Cua VM (`dev`) is the same one used by `v2-automation`. YouTube and TikTok
are already signed in on this machine; Everygen must be signed in once.

```bash
cd /home/zenda/gta_Automation
source .venv/bin/activate

# Start/recover the VM, create directories, deploy guest scripts
python -m pipeline.run prepare

# Open YouTube Studio, TikTok Studio and Everygen in the VM and leave it open
python -m pipeline.run open-logins
```

`open-logins` prints a `view_url`. Open it in a browser **on this machine**,
then:

1. Sign in to Everygen (`Sign in` → Google or email).
2. Confirm YouTube Studio still shows your channel.
3. Confirm TikTok Studio still shows the upload page.

Then verify all three sessions:

```bash
python -m pipeline.run accounts
```

Expected: `"ok": true` and `logged_in: true` for `youtube`, `tiktok` and
`everygen`. If `everygen` is false, sign in again and repeat.

> Running `accounts`, `generate`, `cycle` or `worker` closes any Firefox
> window currently open in the VM and relaunches it with the same profile. Do
> not run two pipeline commands at once; the guest lock serializes browser
> jobs, but the UI is still one Firefox profile.

---

## 3. Daily operation

```bash
# 1. Scrape public YouTube results and store new GTA 6 links
python -m pipeline.run discover

# 2. Generate one short per pending variant in Everygen (VM, paid credits)
python -m pipeline.run generate

# 3. Dry-run publish: uploads reach the review screen but are not posted
python -m pipeline.run publish

# 4. One full cycle, dry run
python -m pipeline.run cycle

# 5. One full cycle, live publish
python -m pipeline.run cycle --live

# 6. Repeat forever (default every hour)
python -m pipeline.run worker --live --interval 3600
```

Preview what will happen without spending credits or touching a platform:

```bash
python -m pipeline.run status
python -m pipeline.run links
python -m pipeline.run generations
python -m pipeline.run posts
python -m pipeline.run runs
python -m pipeline.run events
```

The dashboard's **Shorts Pipeline** view shows the same state read-only.

To run the worker under systemd (user service), copy the sample unit and edit
`--dry-run` to `--live` only after a successful dry-run review:

```bash
mkdir -p ~/.config/systemd/user
cp pipeline/gta-pipeline-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gta-pipeline-worker
journalctl --user -u gta-pipeline-worker -f
```

### What one cycle does

1. Refuses to run if the control tower emergency stop is active.
2. Starts/reuses the Cua VM and redeploys the guest scripts.
3. Checks the three browser sessions (Everygen is required; YouTube/TikTok
   are required only when their platform is enabled).
4. Scrapes the configured queries, ranks results and stores up to
   `PIPELINE_LINKS_PER_CYCLE` new links.
5. For each link, generates up to `PIPELINE_VARIANTS_PER_LINK` shorts in
   Everygen Shorts Studio using the `GTA 6` format. Variants rotate through
   distinct directions and titles (`Neon Drift`, `Beachfront Chaos`,
   `Swamp Crossing`, `Tank Run`) so one source does not produce near-duplicate
   posts.
6. Copies each downloaded MP4 to `data/pipeline/videos/`, probes it with
   `ffprobe`, rejects non-vertical output, and queues publish rows.
7. Publishes each ready short to YouTube and TikTok. `--live` clicks the final
   button; without it the guest scripts stop on the review screen and record a
   `dry_run` post.
8. Records a run, events and evidence. Re-running is idempotent: links are
   unique by URL, generations by `(link_id, variant)`, posts by
   `(generation_id, platform)`.

---

## 4. Configuration

All variables live in `.env` (see `.env.example`). The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `CUA_ENABLED` | `false` | Must be true for the pipeline to touch the VM |
| `CUA_SANDBOX_NAME` | `dev` | Cua VM name |
| `CUA_GUEST_PROFILE` | Firefox profile in the VM | The signed-in sessions |
| `PIPELINE_QUERIES` | GTA 6 queries | Comma-separated YouTube searches |
| `PIPELINE_LINKS_PER_CYCLE` | `3` | Max new links per cycle |
| `PIPELINE_VARIANTS_PER_LINK` | `2` | Shorts requested per source |
| `PIPELINE_MAX_SHORTS_PER_CYCLE` | `4` | Hard cap; variants are reduced if needed |
| `EVERYGEN_FORMAT` | `GTA 6` | Everygen Shorts Studio format |
| `EVERYGEN_CREDIT_BUDGET` | `200` | Daily credit cap; `0` = no host-side cap |
| `EVERYGEN_ESTIMATED_CREDITS` | `39` | Used to stop before a paid generation |
| `EVERYGEN_TIMEOUT` | `1800` | Max seconds for one generation |
| `EVERYGEN_AUTO_APPROVE` | `true` | Click the credit confirmation dialog |
| `PIPELINE_PLATFORMS` | `youtube,tiktok` | Enabled publishers |
| `PIPELINE_LIVE` | `false` | Default for `cycle`/`worker`/`publish` |
| `PIPELINE_DAILY_LIMIT_YOUTUBE` | `3` | Live posts per UTC day |
| `PIPELINE_DAILY_LIMIT_TIKTOK` | `3` | Live posts per UTC day |
| `PIPELINE_REQUIRE_AUTH_CHECK` | `true` | Stop the cycle if a session is lost |
| `PIPELINE_RESPECT_EMERGENCY_STOP` | `true` | Read `factory.db` before every cycle |
| `PIPELINE_RETRY_LIMIT` | `2` | Failed variants/posts retried this many times |

### Everygen plan and budget

Everygen has no free generation plan. The reviewed account was signed in but
showed **“Pick a plan to make this short”** (Starter, Pro, Creator). The
pipeline detects this paywall and returns `PLAN_REQUIRED` instead of spending
time or credits; the draft prompt is saved in the VM. Subscribe / top up on the
account, or sign in with an account that already has credits, then re-run the
generation.

Everygen charges credits per generated clip (the GTA 6 format showed
**39 credits** at 720p/10s on the reviewed build). Set a daily ceiling:

```env
EVERYGEN_CREDIT_BUDGET=400
EVERYGEN_ESTIMATED_CREDITS=39
```

The host stops before starting a variant when the day's recorded credits plus
the estimate exceed the ceiling. The guest script also refuses a clip whose
button cost exceeds the remaining budget. `0` disables the host-side ceiling
but Everygen's own account limit still applies; a limit error is recorded and
the cycle stops cleanly. The shipped default is a conservative **200 credits
per UTC day** (~5 GTA 6 clips at the reviewed 39-credit price).

### Manual credit approval

Set `EVERYGEN_AUTO_APPROVE=false` to stop at the credit dialog. The guest
script returns `APPROVAL_REQUIRED` and the cycle records a failure; approve the
dialog manually in the VM and run the generation again. This is intended for
the first few runs while you calibrate costs.

---

## 5. State, evidence and recovery

```text
data/pipeline/
  pipeline.db          # links, generations, posts, runs, events, kv
  videos/              # downloaded Everygen MP4s
  evidence/            # screenshot.png + page.html per guest job
  logs/                # host job JSON, cua.log, guest stderr
  screenshots/         # cua sb screenshot output
  .guest.lock          # serializes Firefox jobs
```

Useful recovery commands:

```bash
# Release rows left mid-flight by a crash (does not delete videos)
python -m pipeline.run reset-stuck

# Inspect recent failures
python -m pipeline.run events --limit 50
python -m pipeline.run generations --status failed
python -m pipeline.run posts --status failed

# Curate sources without deleting anything
python -m pipeline.run skip-link --id 4 --reason "duplicate trailer"
python -m pipeline.run requeue-link --id 4

# Take a VM screenshot
python -m pipeline.run sandbox screenshot
```

A stopped QEMU VM after a host reboot is recovered automatically by
`prepare`/`cycle` (`cua sb restart` cannot relaunch a stopped QEMU VM; the
pipeline relaunches the saved QEMU cmdline and waits for SSH).

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `Everygen is not signed in` | Run `open-logins`, sign in, then `accounts` |
| `PLAN_REQUIRED` | The Everygen account is signed in but has no active plan/credits. Open everygen.ai in the VM, choose a plan (the reviewed modal showed Starter 200 credits/mo, Pro 500+500, Creator 1000+1000) or sign in with an account that has credits. The source link and prompt are saved; re-run `generate` after checkout |
| `FORMAT_NOT_SELECTED` | Everygen changed the Shorts Studio UI. Open the VM, select GTA 6 manually, inspect `data/pipeline/evidence/.../page.html`, and update `guest_everygen.py` selectors |
| `DOWNLOAD_FAILED` | Open the source evidence screenshot/HTML; the result viewer may require a different download control. The guest also falls back to the video URL and blob fetch |
| `guest job timed out` | Generation can take 20+ min; raise `EVERYGEN_TIMEOUT`. The guest writes a screenshot on timeout |
| `TikTok post did not confirm` | TikTok may show a copyright/processing interstitial; the guest clicks `Post now`. Check the evidence screenshot |
| `YouTube publish did not confirm` | The guest verifies PUBLIC and only clicks Save/Publish after the radio reads back checked; a private publish is treated as a failure |
| `NOT_LOGGED_IN` after a long time | Platform sessions expire; sign in again in the VM. The VM disk is never deleted by the pipeline |
| `daily ... publish limit reached` | Rows are marked `deferred` and retried on the next cycle; raise the limit deliberately or wait for the next UTC day |
| VM state `stopped` | `python -m pipeline.run prepare` (recovers QEMU) |
| Two pipeline commands at once | Wait; the guest lock serializes browser jobs |
| v2-automation CUA publish running at the same time | Do not run both pipelines concurrently: they share the same Firefox profile and will kill each other's browser. Run them sequentially |

---

## 7. Safety and platform policy

- **No API keys, no password storage.** The pipeline uses the interactive
  browser profile the owner signed in to. It does not read, type or store
  credentials.
- **No CAPTCHA or rate-limit bypass.** If a platform challenges the session,
  the job fails and leaves evidence; the owner resolves it in the VM.
- **Dry run is the default.** Live posting requires `--live` or
  `PIPELINE_LIVE=true`, and per-platform daily caps are enforced before the
  upload starts.
- **AI disclosure.** YouTube descriptions include an AI-generated disclosure.
  Check current YouTube and TikTok synthetic-media disclosure rules before
  posting; add platform-native disclosure labels where required.
- **Rights and platform policy are the owner's responsibility.** The pipeline
  uses a source video only as topic inspiration and explicitly instructs
  Everygen to create original footage, not to reuse source footage, logos,
  characters or music. Do not configure it to clone or repost third-party
  footage you do not have rights to. The existing Founder Control Tower's
  rights gate remains the policy reference.
- **The control tower emergency stop wins.** If `factory.db` has
  `emergency_stop = true`, the pipeline refuses to start a cycle.

---

## 8. Extending the Everygen flow

The current default uses **Shorts Studio → GTA 6 format**. The source YouTube
URL and title are embedded in the short direction as a reference, and the
format produces a fresh 9:16 clip with sound.

If you want Everygen's Wizard to ingest the link itself (Download tool), the
place to add it is `pipeline/guest/guest_everygen.py`: add a `--workflow wizard`
branch that opens `/tools/wizard`, sends the link plus a GTA 6 direction, and
polls the assistant's generated result before using the same download helpers.
Keep the `--workflow shorts_studio` path as the stable default until the
Wizard selectors are verified against the live account.
