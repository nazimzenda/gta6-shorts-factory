# Final project status — CUA Shorts Pipeline

**Date:** 2026-11-08
**Status:** Software complete. **Free clip mode is finished and tested end-to-end.**
Everygen AI mode is optional and still requires an Everygen plan/credits.

---

## 0. Free clip mode (the route for "just clip YouTube links")

**Complete and tested.** No Everygen, no credits, no watermark.

```text
YouTube link
  → yt-dlp metadata + captions
  → caption keyword/density highlight selection
  → yt-dlp section download (or full download for short videos)
  → FFmpeg 1080×1920 vertical clip
  → blurred-background "fit" layout (or center-crop)
  → title + burned-in captions when available
  → existing YouTube/TikTok CUA publisher
```

Tested on:

- **Big Buck Bunny** (Creative Commons) — 20s clip, 1080×1920, 5.8 MB
- **Rockstar Updated the GTA 6 Release Time** — two 35s clips, 1080×1920,
  full gameplay + facecam on a blurred background, with burned-in subtitles

Subtitles and layout:

- YouTube captions are tried first.
- YouTube rate-limited this IP with `429`, so the clipper fell back to **local
  Whisper** and produced **82 caption segments** for the 3:58 source.
- The default **`streamer` layout** fills the full 1080×1920 frame (no blurred
  or black bars), keeps the facecam in a clean top-right PiP, and puts bold
  captions in the bottom safe area.
- Caption fixes are applied before rendering; `Viciti` is corrected to
  `Vice City` in both the burned-in subtitles and the `.srt`.
- The title overlay is off by default; captions are on by default.

Dashboard:

- **Add YouTube sources** form for multiple links / multiple people.
- **Clip showcase** gallery with an HTML5 player.
- **Play** link on every local clip.
- **Publish live** button with explicit public-action + rights confirmations.
- Publish attempts and background clip/publish jobs appear in the same view.
- **CUA Sessions** tab now shows the live pipeline CUA VM at the top with a viewer link, separate from the approval-broker sessions.

Commands:

```bash
python -m pipeline.run clip --url "https://www.youtube.com/watch?v=..." \
  --count 2 --rights-ack

python -m pipeline.run cycle --mode clip --rights-ack --live
```

The rights gate is deliberate: only clip videos you own or have permission to
reuse. See [CLIP_MODE.md](./CLIP_MODE.md).

---

## 1. What is complete

| Component | Status |
|---|---|
| Cua VM lifecycle (start / resume / recover / status / screenshot / view) | Complete |
| Host ↔ guest deployment and detached long-job protocol | Complete |
| YouTube GTA 6 discovery (public search, no API key) | Complete |
| Source ranking, URL + title dedupe, manual skip/requeue | Complete |
| Everygen Shorts Studio automation (GTA 6 format, prompt, Generate, result detection) | Complete |
| Everygen result download (download controls, direct URL, blob fallback) | Complete |
| MP4/WebM container sniff + ffprobe QC + vertical check | Complete |
| YouTube Studio browser publishing (dry-run and live) | Complete |
| TikTok Studio browser publishing (dry-run and live) | Complete |
| Idempotent pipeline DB, retries, deferred limits, daily caps | Complete |
| Everygen credit budget / plan-paywall detection | Complete |
| Control-tower emergency-stop respect | Complete |
| CLI (`prepare`, `open-logins`, `accounts`, `discover`, `generate`, `publish`, `cycle`, `worker`, `status`, `links`, `generations`, `posts`, `runs`, `events`, `skip-link`, `requeue-link`, `reset-stuck`) | Complete |
| Dashboard **Shorts Pipeline** view | Complete |
| systemd worker sample | Complete |
| Documentation and runbook | Complete |
| Tests | **67 passed** |

Verified against the live services:

- Cua VM `dev` running.
- YouTube Studio session logged in.
- TikTok Studio session logged in.
- Everygen session logged in (`/api/auth/get-session` returns a user).
- Everygen Shorts Studio Selenium self-test: GTA 6 format selected, prompt
  typed, Generate button enabled at **39 credits**, completed result card
  detected (`Completed`, `Open video: …`).

---

## 2. Everygen AI mode — optional paid route

**This section does not block free clip mode.** Use it only if you want
Everygen to generate new AI footage instead of clipping a YouTube source.

The Everygen account is signed in but **has no active plan or credits**.
Clicking Generate opens:

> **Pick a plan to make this short**
> Your draft is saved. You'll come right back here after checkout.
>
> Starter — 200 credits/mo
> Pro — 500 credits/mo + 500 bonus
> Creator — 1,000 credits/mo + 1,000 bonus

The pipeline now detects this automatically and returns `PLAN_REQUIRED`
instead of looping or spending time. The failed attempt was reset:

- link `10` is back in `new`
- generation `3` is `deferred` with `PLAN_REQUIRED`

The VM shows a message:
**“Couldn't load the security check. An ad blocker or privacy extension is the
usual cause. Try again.”** If checkout fails, disable the ad blocker/privacy
extension for everygen.ai or use a browser/profile without it.

---

## 2b. Dry-run publish result (2026-11-08)

Both fixed clips were uploaded to the real platform review screens through the
Cua VM:

| Clip | YouTube | TikTok |
|---|---|---|
| clip00005 | `dry_run` — stopped at review | `dry_run` — stopped before Post |
| clip00006 | `dry_run` — stopped at review | `dry_run` — stopped before Post |

**4/4 dry runs, 0 failures, nothing published publicly.** The first TikTok
attempt for clip00005 hit a geckodriver read timeout; a retry completed
successfully. This is recorded in the pipeline DB and dashboard.

---

## 3. Resume after subscribing / topping up

1. Open the CUA viewer and complete Everygen checkout, **or** sign out and sign
   in with an Everygen account that already has credits.
2. Verify all three sessions:

   ```bash
   cd /home/zenda/gta_Automation
   source .venv/bin/activate
   python -m pipeline.run accounts
   ```

3. Generate one short from the already discovered GTA 6 link:

   ```bash
   python -m pipeline.run generate --link-id 10 --variants 1
   ```

4. Review the downloaded file:

   ```bash
   python -m pipeline.run generations
   ls -lh data/pipeline/videos
   ```

5. Dry-run both platform uploads:

   ```bash
   python -m pipeline.run publish --dry-run
   ```

6. If the review screens are correct, publish live:

   ```bash
   python -m pipeline.run publish --live
   ```

7. Run the autonomous loop:

   ```bash
   python -m pipeline.run cycle --live
   # or
   python -m pipeline.run worker --live --interval 3600
   ```

---

## 4. Defaults

- Dry-run unless `--live` or `PIPELINE_LIVE=true`.
- 2 variants per link; max 4 shorts per cycle.
- 200 Everygen credits per UTC day (~5 clips at 39 credits).
- 3 YouTube posts/day and 3 TikTok posts/day.
- `PIPELINE_REQUIRE_AUTH_CHECK=true`.
- `PIPELINE_RESPECT_EMERGENCY_STOP=true`.
- No platform API keys. No password storage. No CAPTCHA bypass.

---

## 5. Key files

```text
pipeline/
  config.py              environment + caps
  cua_sandbox.py         Cua CLI wrapper + QEMU recovery
  guest_runner.py        deploy, detached jobs, evidence
  yt_search.py           public YouTube discovery
  everygen.py            prompt, download, QC, credits/plan handling
  publish.py             YouTube/TikTok metadata and posting
  orchestrator.py        cycle, worker, emergency stop
  run.py                 CLI
  guest/
    guest_accounts.py    login checks
    guest_everygen.py    Everygen Shorts Studio driver
    upload_yt.py         YouTube Studio uploader
    upload_tiktok.py     TikTok Studio uploader
    guest_open_logins.py one-time sign-in tabs
  gta-pipeline-worker.service
docs/
  CUA_PIPELINE.md        full runbook
  FINAL_STATUS.md        this file
```

Dashboard: <http://127.0.0.1:8000> → **Shorts Pipeline**.
