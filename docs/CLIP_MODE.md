# Free Clip Mode — YouTube link → vertical highlights

This mode does **not** use Everygen, Veo, Kling, Dreamina or any paid API. It
downloads a public YouTube source with `yt-dlp`, reads the video's own
captions/subtitles to find strong moments, and cuts 1080×1920 vertical clips
with FFmpeg. No watermark, no monthly minute limit, no API key.

> **Rights gate:** clipping and republishing someone else's stream is a
> copyright decision. Only run this on videos you own or have permission to
> reuse. Every clip description includes the source title and URL, and the
> command requires an explicit acknowledgement.

---

## 1. What it produces

- 9:16 vertical MP4, 1080×1920, H.264 + AAC
- **`streamer` layout (default)**: the core video is center-cropped to fill the
  full frame (no blurred/black padding), and the streamer's facecam is lifted
  into a clean top-right PiP with a white border
- `crop` layout: fill the frame by center-cropping only
- `fit` layout: full source frame on a blurred background (useful when no
  content can be cut)
- Burned-in captions when available: the video's YouTube captions first, then a
  **local Whisper transcription fallback** if YouTube rate-limits the subtitle
  endpoint. Captions are bottom-centered, bold, with a black outline/shadow and
  do not overlap the facecam PiP.
- Caption typo fixes (default: `Viciti` → `Vice City`)
- Optional burned-in title (`PIPELINE_CLIP_SHOW_TITLE`, default `false`)
- Sidecar `.srt` next to the MP4
- **No provider watermark.** The only overlays are the optional title and the
  captions; set `PIPELINE_CLIP_SHOW_CAPTIONS=false` for a completely clean
  video (the SRT sidecar is still written).
- The clip is stored as a normal pipeline generation, so the existing
  YouTube/TikTok publisher and dry-run/live gates apply unchanged

Tested end-to-end on a GTA 6 news video:

```text
source: Rockstar Updated the GTA 6 Release Time (3:58)
output: 25s, 1080x1920, 6.7 MB, full frame + blurred background
```

---

## 2. One-time requirements

- `ffmpeg` and `ffprobe` (installed)
- `yt-dlp` (installed in `.venv`; also added to `pyproject.toml`)
- A public YouTube link
- `PIPELINE_RIGHTS_ACK=true` or `--rights-ack` on the command

Check:

```bash
cd /home/zenda/gta_Automation
source .venv/bin/activate
ffmpeg -version
.venv/bin/yt-dlp --version
python -m pipeline.run status
```

`status` should show:

```json
"mode": "clip"
```

---

## 3. Commands

### One YouTube link → 2 clips

```bash
python -m pipeline.run clip \
  --url "https://www.youtube.com/watch?v=uDs1IrGu87I" \
  --count 2 \
  --rights-ack
```

### One already-discovered link from the pipeline queue

```bash
python -m pipeline.run links
python -m pipeline.run clip --link-id 10 --count 2 --rights-ack
```

### Manual time window (bypasses highlight selection)

```bash
python -m pipeline.run clip \
  --url "https://www.youtube.com/watch?v=..." \
  --start 125 --end 150 \
  --rights-ack
```

### Full automatic cycle

```bash
# dry-run: clips are made and uploaded to the platform review screens
python -m pipeline.run cycle --mode clip --rights-ack

# live publish
python -m pipeline.run cycle --mode clip --rights-ack --live

# repeat every hour
python -m pipeline.run worker --mode clip --rights-ack --live --interval 3600
```

The cycle discovers GTA 6 links, clips the new ones, QC-checks the vertical
output, then uses the existing YouTube/TikTok CUA publisher.

### Publish existing clips

```bash
python -m pipeline.run publish --dry-run
python -m pipeline.run publish --live
```

---

## 3b. Dashboard controls

Open <http://127.0.0.1:8000> → **Shorts Pipeline**.

- **Add YouTube sources** card: paste one or more links (one per line), choose
  clips per source, tick the rights acknowledgement, and press **Queue & clip**.
  The job runs in the background; refresh the view to see the new clips.
- **Clip showcase** button: watch every rendered MP4 in a simple gallery.
- **Local clips** table: each row has a **Play** link and the exact file path.
- **Publish attempts**: 4 rows per clip (YouTube + TikTok), with dry-run/live
  status. **DRY RUN is not public**; only `PUBLISHED` rows exist on the platforms.
- **Publish live** button: opens a confirmation modal with two checkboxes
  (public action + rights). It starts a background live-publish job through the
  CUA VM. The rows change from `DRY RUN` to `PUBLISHED` when done.
- **Recent cycles**: background clip jobs, publish jobs and pipeline cycles are
  recorded here.
- **CUA Sessions** tab: the top card is the **live pipeline CUA VM** with the
  viewer link. The approval-broker sessions below are a separate control-tower
  feature.

The dashboard uses the same `PIPELINE_RIGHTS_ACK` model: the form requires the
“I have permission to reuse these videos” checkbox. Only one background clip
job runs at a time.

---

## 4. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PIPELINE_MODE` | `clip` | `clip` = local highlights; `generate` = Everygen |
| `PIPELINE_RIGHTS_ACK` | `false` | Required for clip mode |
| `PIPELINE_CLIPS_PER_VIDEO` | `2` | Clips requested per source |
| `PIPELINE_CLIP_MIN_SECONDS` | `15` | Minimum clip length |
| `PIPELINE_CLIP_MAX_SECONDS` | `60` | Maximum clip length |
| `PIPELINE_CLIP_TARGET_SECONDS` | `35` | Preferred highlight window |
| `PIPELINE_CLIP_QUALITY` | `1080` | Max source height |
| `PIPELINE_CLIP_LAYOUT` | `streamer` | `streamer` (full-frame + facecam PiP), `crop`, or `fit` |
| `PIPELINE_CLIP_FACECAM_CROP` | `0.80,0.00,1.00,0.30` | Normalized `x1,y1,x2,y2` facecam region in the source |
| `PIPELINE_CLIP_FACECAM_WIDTH` | `280` | Facecam PiP width in output pixels |
| `PIPELINE_CLIP_FACECAM_MARGIN` | `36` | Facecam PiP margin from the top/right |
| `PIPELINE_CLIP_CAPTION_SIZE` | `12` | ASS caption font size (scaled to 1080×1920) |
| `PIPELINE_CLIP_CAPTION_MARGIN` | `24` | Distance from the bottom safe area |
| `PIPELINE_CLIP_CAPTION_FIXES` | `Viciti=Vice City` | Comma-separated `wrong=right` caption corrections |
| `PIPELINE_CLIP_SHOW_TITLE` | `false` | Burn the short title at the top; `false` = clean video |
| `PIPELINE_CLIP_SHOW_CAPTIONS` | `true` | Burn captions when available; `false` = clean video (SRT sidecar still written) |
| `PIPELINE_CLIP_TRANSCRIBE_FALLBACK` | `true` | Use local Whisper when YouTube captions fail or are absent |
| `PIPELINE_WHISPER_PYTHON` | sibling v2 venv | Python environment with `openai-whisper` + torch |
| `PIPELINE_WHISPER_MODEL` | `base` | Whisper model size (`base`, `small`, `medium`, `large`) |
| `PIPELINE_WHISPER_TIMEOUT` | `900` | Max seconds for a local transcription |
| `PIPELINE_CLIP_MAX_SOURCE_SECONDS` | `7200` | Refuse longer sources |
| `PIPELINE_CLIP_MAX_FULL_DOWNLOAD_SECONDS` | `900` | Full download under 15 min; sections above |
| `PIPELINE_CLIP_DOWNLOAD_TIMEOUT` | `1200` | yt-dlp timeout |
| `PIPELINE_CLIP_RENDER_TIMEOUT` | `600` | FFmpeg timeout |
| `PIPELINE_CLIP_SUBTITLE_LANGS` | `en.*,en` | Preferred caption languages |
| `PIPELINE_CLIP_TITLE_PREFIX` | `Streamer Moment | GTA 6` | Fallback title suffix |

If `PIPELINE_CLIP_MAX_FULL_DOWNLOAD_SECONDS` is exceeded, the clipper downloads
only the selected sections with `yt-dlp --download-sections`, so a multi-hour
stream does not fill the disk.

---

## 4b. Fixing caption typos

Add one or more `wrong=right` pairs to `.env`:

```env
PIPELINE_CLIP_CAPTION_FIXES=Viciti=Vice City,teh=the
```

The correction is applied to both the burned-in subtitles and the sidecar
`.srt`, case-insensitively, before window selection. The default is already
`Viciti=Vice City`.

## 5. How highlight selection works

1. `yt-dlp --dump-single-json` reads title, duration, channel and caption
   availability.
2. If captions exist, the VTT is downloaded and parsed. YouTube's rolling
   repeated captions are de-duplicated.
3. Consecutive captions are grouped into candidate windows of roughly
   `PIPELINE_CLIP_TARGET_SECONDS`. Each window is scored by GTA/streamer
   keywords, speech density and punctuation.
4. Overlapping candidates are removed; the top non-overlapping windows become
   the clips.
5. If no captions exist, three evenly spaced windows are used (or one window
   when the source is already short).

The result is deterministic and free. It does not use an LLM or paid service.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `yt-dlp ... 429 Too Many Requests` | YouTube is rate-limiting caption downloads. The clipper now falls back to local Whisper automatically; wait a few minutes if the audio download itself is also limited |
| `Sign in to confirm you're not a bot` | The source is bot-protected. Use a public non-protected video or export cookies for yt-dlp |
| `source duration could not be determined` | The URL is not a normal public video, or yt-dlp could not read it |
| `ffmpeg render failed` | Check `ffmpeg -version`; the clipper retries once without cosmetic filters |
| Clip is mostly blurred / facecam small | Use `PIPELINE_CLIP_LAYOUT=crop` for full-screen center crop, or `fit` to keep the full frame |
| No captions burned in | Check `PIPELINE_CLIP_SHOW_CAPTIONS=true`; if the source has no speech, Whisper returns no segments. Verify `PIPELINE_WHISPER_PYTHON` points at an environment with whisper + torch |
| Whisper fallback not running | Install `openai-whisper` and `torch` in a Python env, set `PIPELINE_WHISPER_PYTHON` to that interpreter. On this machine the sibling v2-automation venv already has them |
| `rights` error | Add `--rights-ack` only when you own the source or have permission |
| Disk filling up | Delete `data/pipeline/sources/` after processing; clips live in `data/pipeline/videos/` |

---

## 7. Rights and platform policy

- Only clip videos you **own** or have **explicit permission** to republish.
- Keep the source attribution in the description (the publisher adds it).
- Prefer transformative edits: add your own commentary, context or captions.
- YouTube and TikTok have copyright/reused-content rules. Repeatedly uploading
  unmodified third-party clips can get the account struck or demonetized.
- The pipeline defaults to dry-run. Review the platform upload screens before
  using `--live`.
- The control-tower emergency stop still blocks every cycle.
