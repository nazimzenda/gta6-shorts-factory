"""Free local YouTube clipper.

Turns a public YouTube link into vertical highlight clips using ``yt-dlp``,
the video's own captions/subtitles (when available) and FFmpeg.  No AI video
provider, no API key and no watermark.

This mode is intentionally gated behind an explicit rights acknowledgement:
clipping and republishing someone else's stream is a copyright decision, not a
technical one.  Set ``PIPELINE_RIGHTS_ACK=true`` or pass ``--rights-ack`` only
when you own the source or have permission.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pipeline.config import PipelineSettings
from pipeline.db import PipelineDB
from pipeline.errors import PipelineError
from pipeline.media import is_vertical, looks_like_video, probe_video, safe_stem

LOGGER = logging.getLogger("pipeline.clipper")

# Words that tend to mark a strong short-video moment.  Kept local so clip
# mode does not depend on the control tower's database models.
CLIP_KEYWORDS = {
    "gta",
    "gta6",
    "gta 6",
    "gameplay",
    "mission",
    "police",
    "chase",
    "explosion",
    "glitch",
    "bug",
    "funny",
    "insane",
    "crazy",
    "secret",
    "found",
    "first",
    "best",
    "worst",
    "fail",
    "reaction",
    "wow",
    "no way",
    "unbelievable",
    "actually",
    "watch",
    "look",
    "how",
    "why",
    "new",
    "leak",
    "trailer",
    "stream",
    "clip",
}

_TS_RE = re.compile(
    r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*"
    r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})"
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass
class ClipWindow:
    start: float
    end: float
    score: float
    hook: str
    reason: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# --------------------------------------------------------------------- helpers
def _clean_text(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    text = _WS_RE.sub(" ", text).strip()
    return text


def apply_caption_fixes(text: str, settings: PipelineSettings) -> str:
    value = text or ""
    for wrong, right in (settings.caption_fixes or {}).items():
        if not wrong:
            continue
        value = re.sub(re.escape(wrong), right, value, flags=re.IGNORECASE)
    return value


def _parse_timestamp(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def parse_vtt(path: str | Path) -> list[Segment]:
    """Parse a WebVTT file, dropping YouTube's repeated rolling captions."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    segments: list[Segment] = []
    seen_texts: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        match = _TS_RE.search(line)
        if not match:
            index += 1
            continue
        start = _parse_timestamp(*match.groups()[:4])
        end = _parse_timestamp(*match.groups()[4:8])
        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(_clean_text(lines[index]))
            index += 1
        text = _WS_RE.sub(" ", " ".join(text_lines)).strip()
        if not text:
            continue
        # YouTube auto captions often repeat the previous line or append a
        # rolling fragment. Keep only genuinely new text.
        if seen_texts:
            previous = seen_texts[-1]
            if text == previous or text in previous:
                continue
            if previous and text.startswith(previous):
                text = text[len(previous):].strip()
                if not text:
                    continue
            elif previous.endswith(text):
                continue
        seen_texts.append(text)
        if len(seen_texts) > 8:
            seen_texts.pop(0)
        if end <= start:
            end = start + 1.0
        segments.append(Segment(start=start, end=end, text=text))
    return segments


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _window_text(segments: list[Segment], start: float, end: float) -> str:
    return " ".join(
        segment.text
        for segment in segments
        if segment.end > start and segment.start < end
    ).strip()


def _hook(text: str, fallback: str) -> str:
    cleaned = _URL_RE.sub("", _clean_text(text)).strip(" .!?,-|")
    if not cleaned:
        return fallback
    # Prefer a whole sentence, then a short phrase.
    sentence = re.split(r"(?<=[.!?])\s+", cleaned)[0].strip()
    value = sentence or cleaned
    if len(value) > 78:
        value = value[:77].rsplit(" ", 1)[0].rstrip(" .!?,-|")
    return value or fallback


def select_windows(
    segments: list[Segment],
    duration: float,
    *,
    count: int,
    min_seconds: int,
    max_seconds: int,
    target_seconds: int,
    fallback_title: str = "GTA 6 moment",
) -> list[ClipWindow]:
    """Pick non-overlapping highlight windows from captions or fixed positions."""
    count = max(1, int(count))
    duration = max(0.0, float(duration))
    if duration <= 0:
        return []
    min_seconds = max(3, int(min_seconds))
    max_seconds = max(min_seconds, int(max_seconds))
    target = max(min_seconds, min(int(target_seconds), max_seconds))
    if duration <= max_seconds:
        return [
            ClipWindow(
                start=0.0,
                end=duration,
                score=0.6,
                hook=_hook(
                    _window_text(segments, 0, duration) or fallback_title,
                    fallback_title,
                ),
                reason="source already short enough",
            )
        ]

    candidates: list[ClipWindow] = []
    if segments:
        # Sample starts so a multi-hour stream does not produce an O(n^2) scan.
        step = max(1, len(segments) // 400)
        for segment in segments[::step]:
            start = max(0.0, segment.start - 1.0)
            end = min(duration, start + target)
            if end - start < min_seconds:
                end = min(duration, start + min_seconds)
            if end - start < min_seconds:
                continue
            text = _window_text(segments, start, end)
            if not text:
                continue
            lowered = text.lower()
            hits = sum(1 for keyword in CLIP_KEYWORDS if keyword in lowered)
            density = len(text) / max(1.0, end - start)
            score = (
                0.30
                + min(0.30, hits * 0.055)
                + min(0.22, density / 26.0)
                + (0.05 if "?" in text or "!" in text else 0.0)
            )
            candidates.append(
                ClipWindow(
                    start=round(start, 2),
                    end=round(end, 2),
                    score=round(min(0.99, score), 3),
                    hook=_hook(text, fallback_title),
                    reason=f"caption keywords={hits}, density={density:.1f} chars/s",
                )
            )
    if not candidates:
        positions = [0.08, 0.38, 0.68] if count >= 3 else [0.12, 0.52]
        for index, position in enumerate(positions[:count]):
            start = min(max(0.0, duration * position), max(0.0, duration - min_seconds))
            end = min(duration, start + target)
            candidates.append(
                ClipWindow(
                    start=round(start, 2),
                    end=round(end, 2),
                    score=round(0.55 - index * 0.04, 3),
                    hook=f"{fallback_title} - clip {index + 1}",
                    reason="duration heuristic; no captions available",
                )
            )
    candidates.sort(key=lambda window: window.score, reverse=True)
    selected: list[ClipWindow] = []
    for candidate in candidates:
        if any(
            _overlap(candidate.start, candidate.end, other.start, other.end)
            / max(1.0, min(candidate.end, other.end) - max(candidate.start, other.start))
            > 0.40
            for other in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= count:
            break
    selected.sort(key=lambda window: window.start)
    return selected or candidates[:count]


def _srt_time(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_clip_srt(
    segments: Iterable[Segment],
    window_start: float,
    window_end: float,
    output_path: Path,
) -> Path | None:
    cues: list[str] = []
    for segment in segments:
        if segment.end <= window_start or segment.start >= window_end:
            continue
        start = max(segment.start, window_start) - window_start
        end = min(segment.end, window_end) - window_start
        if end <= start:
            continue
        text = _clean_text(segment.text)
        if not text:
            continue
        cues.append(
            f"{len(cues) + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n"
        )
    if not cues:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(cues), encoding="utf-8")
    return output_path


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
        .replace("\n", " ")
    )


def _font_path() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


# ------------------------------------------------------------------- yt-dlp
def _ytdlp(settings: PipelineSettings) -> list[str]:
    if settings.yt_dlp_bin:
        return [settings.yt_dlp_bin]
    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]
    return [sys.executable, "-m", "yt_dlp"]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as error:
        raise PipelineError(
            f"command timed out after {timeout}s: {' '.join(command[:4])}..."
        ) from error
    except OSError as error:
        raise PipelineError(f"could not run {command[0]}: {error}") from error


def fetch_info(url: str, settings: PipelineSettings) -> dict[str, Any]:
    command = [
        *_ytdlp(settings),
        "--dump-single-json",
        "--no-warnings",
        "--no-playlist",
        "--skip-download",
        url,
    ]
    result = _run(command, timeout=180)
    if result.returncode != 0:
        raise PipelineError(
            f"yt-dlp could not read the source: {(result.stderr or result.stdout)[-800:]}"
        )
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError as error:
        raise PipelineError("yt-dlp returned invalid metadata JSON") from error
    if not isinstance(data, dict):
        raise PipelineError("yt-dlp returned an unexpected metadata payload")
    return data


def _choose_language(info: dict[str, Any], wanted: str) -> str | None:
    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    available = list(subtitles.keys()) or list(automatic.keys())
    if not available:
        return None
    wanted_parts = [part.strip() for part in wanted.split(",") if part.strip()]
    for pattern in wanted_parts:
        prefix = pattern.rstrip(".*")
        for language in available:
            if language == prefix or language.startswith(prefix):
                return language
    for language in available:
        if language.startswith("en"):
            return language
    return available[0]


def download_subtitles(
    url: str, info: dict[str, Any], workdir: Path, settings: PipelineSettings
) -> Path | None:
    language = _choose_language(info, settings.clip_subtitle_langs)
    if not language:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    command = [
        *_ytdlp(settings),
        "--no-playlist",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        language,
        "--sub-format",
        "vtt",
        "--convert-subs",
        "vtt",
        "--sleep-requests",
        "1",
        "--no-warnings",
        "--output",
        str(workdir / "%(id)s.%(ext)s"),
        url,
    ]
    last_error = ""
    for attempt in range(3):
        result = _run(command, timeout=240)
        candidates = sorted(
            workdir.glob("*.vtt"), key=lambda path: path.stat().st_mtime
        )
        if candidates:
            return candidates[-1]
        last_error = (result.stderr or result.stdout or "")[-500:]
        if "429" in last_error or "too many requests" in last_error.lower():
            time.sleep(5 * (attempt + 1))
            continue
        break
    if last_error:
        LOGGER.warning("subtitle download failed for %s: %s", url, last_error[-400:])
    return None


def _find_media(workdir: Path) -> Path | None:
    extensions = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
    files = [
        path
        for path in workdir.iterdir()
        if path.is_file() and path.suffix.lower() in extensions and path.stat().st_size > 10_000
    ]
    if not files:
        return None
    # Prefer MP4, then the largest file.
    files.sort(key=lambda path: (path.suffix.lower() != ".mp4", -path.stat().st_size))
    return files[0]


def download_full(
    url: str, info: dict[str, Any], workdir: Path, settings: PipelineSettings
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    video_id = safe_stem(str(info.get("id") or "source"), "source", 20)
    command = [
        *_ytdlp(settings),
        "--no-playlist",
        "--format",
        f"bestvideo[height<={settings.clip_quality}]+bestaudio/"
        f"best[height<={settings.clip_quality}]",
        "--merge-output-format",
        "mp4",
        "--no-warnings",
        "--output",
        str(workdir / f"{video_id}.%(ext)s"),
        url,
    ]
    result = _run(command, timeout=settings.clip_download_timeout)
    media = _find_media(workdir)
    if result.returncode != 0 or media is None:
        raise PipelineError(
            f"yt-dlp download failed: {(result.stderr or result.stdout)[-800:]}"
        )
    return media


def download_section(
    url: str,
    info: dict[str, Any],
    workdir: Path,
    start: float,
    end: float,
    index: int,
    settings: PipelineSettings,
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    video_id = safe_stem(str(info.get("id") or "source"), "source", 20)
    section = f"*{max(0.0, start):.1f}-{max(start + 1.0, end):.1f}"
    command = [
        *_ytdlp(settings),
        "--no-playlist",
        "--download-sections",
        section,
        "--force-keyframes-at-cuts",
        "--format",
        f"bestvideo[height<={settings.clip_quality}]+bestaudio/"
        f"best[height<={settings.clip_quality}]",
        "--merge-output-format",
        "mp4",
        "--no-warnings",
        "--output",
        str(workdir / f"{video_id}-section{index}.%(ext)s"),
        url,
    ]
    result = _run(command, timeout=settings.clip_download_timeout)
    candidates = sorted(
        (
            path
            for path in workdir.glob(f"{video_id}-section{index}.*")
            if path.is_file()
            and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
        ),
        key=lambda path: path.stat().st_mtime,
    )
    if result.returncode != 0 or not candidates:
        raise PipelineError(
            f"yt-dlp section download failed: {(result.stderr or result.stdout)[-800:]}"
        )
    return candidates[-1]


# ------------------------------------------------------------- transcription
def _extract_audio(source_path: Path, output_path: Path, timeout: int = 300) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise PipelineError("ffmpeg is required to extract audio for transcription")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        timeout=timeout,
    )
    if result.returncode != 0 or not output_path.is_file():
        raise PipelineError(
            f"audio extraction failed: {(result.stderr or result.stdout)[-600:]}"
        )
    return output_path


def _whisper_python(settings: PipelineSettings) -> str | None:
    candidates: list[str] = []
    if settings.whisper_python:
        candidates.append(settings.whisper_python)
    if importlib.util.find_spec("whisper") is not None:
        candidates.append(sys.executable)
    # Known sibling environment on this machine; still only a fallback.
    candidates.append("/home/zenda/v2-automation/venv/bin/python")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def transcribe_local(
    source_path: Path, workdir: Path, settings: PipelineSettings
) -> list[Segment]:
    """Transcribe a downloaded source with local Whisper (no API key)."""
    if not settings.clip_transcribe_fallback:
        return []
    python = _whisper_python(settings)
    if not python:
        LOGGER.warning(
            "no Whisper environment found; captions unavailable for this source"
        )
        return []
    try:
        audio = _extract_audio(source_path, workdir / "audio.wav")
    except PipelineError as error:
        LOGGER.warning("Whisper audio extraction failed: %s", error)
        return []
    worker = Path(__file__).with_name("whisper_worker.py")
    if not worker.is_file():
        LOGGER.warning("Whisper worker missing at %s", worker)
        return []
    LOGGER.info("transcribing %s with local Whisper (%s)", source_path.name, settings.whisper_model)
    result = _run(
        [
            python,
            str(worker),
            "--audio",
            str(audio),
            "--model",
            settings.whisper_model,
            "--language",
            "en",
        ],
        timeout=settings.whisper_timeout,
    )
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        payload = {}
    if result.returncode != 0 or payload.get("error"):
        LOGGER.warning(
            "Whisper fallback failed: %s",
            payload.get("error") or (result.stderr or result.stdout)[-400:],
        )
        return []
    segments = [
        Segment(
            start=float(item.get("start") or 0.0),
            end=float(item.get("end") or 0.0),
            text=str(item.get("text") or "").strip(),
        )
        for item in payload.get("segments", [])
        if str(item.get("text") or "").strip()
    ]
    LOGGER.info("Whisper produced %s caption segments", len(segments))
    return segments


# --------------------------------------------------------------------- render
def render_clip(
    source_path: Path,
    start: float,
    end: float,
    output_path: Path,
    *,
    title: str,
    segments: list[Segment],
    window_start: float,
    window_end: float,
    settings: PipelineSettings,
) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise PipelineError("ffmpeg and ffprobe are required for clip rendering")
    duration = max(0.5, end - start)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    has_audio = True
    # probe_video does not expose has_audio; ask ffprobe once directly.
    try:
        audio_probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        has_audio = bool((audio_probe.stdout or "").strip())
    except (OSError, subprocess.TimeoutExpired):
        has_audio = True

    srt_path = write_clip_srt(
        segments,
        window_start,
        window_end,
        output_path.with_suffix(".srt"),
    )
    width, height = 1080, 1920
    font = _font_path()
    title_filter = ""
    if font and title and settings.clip_show_title:
        overlay = _clean_text(title)
        if len(overlay) > 42:
            overlay = overlay[:41].rsplit(" ", 1)[0].rstrip(" .!?,-|") + "…"
        title_filter = (
            "drawtext="
            f"fontfile={font}:"
            f"text='{_escape_drawtext(overlay)}':"
            "fontcolor=white:fontsize=38:line_spacing=8:"
            "box=1:boxcolor=black@0.62:boxborderw=14:"
            "x=(w-text_w)/2:y=84"
        )
    subtitle_filter = ""
    if srt_path is not None and settings.clip_show_captions:
        escaped = str(srt_path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
        subtitle_filter = (
            f"subtitles={escaped}:force_style='"
            "FontName=DejaVu Sans,"
            f"FontSize={max(8, int(settings.clip_caption_size))},"
            "Alignment=2,"
            f"MarginV={max(4, int(settings.clip_caption_margin))},"
            "Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1'"
        )
    crop_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30"
    )
    filters = [crop_filter]
    if title_filter:
        filters.append(title_filter)
    if subtitle_filter:
        filters.append(subtitle_filter)
    input_args = [
        ffmpeg,
        "-y",
        "-ss",
        f"{max(0.0, start):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source_path),
    ]
    codec_args = [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
    ]
    audio_args = ["-c:a", "aac", "-b:a", "128k"] if has_audio else ["-an"]
    tail = ["-movflags", "+faststart", str(output_path)]
    layout = (settings.clip_layout or "streamer").lower()
    use_fit = layout == "fit"
    use_streamer = layout == "streamer"
    source_probe = probe_video(source_path)
    src_w = int(source_probe.get("width") or 0)
    src_h = int(source_probe.get("height") or 0)

    # Full-frame 9:16 crop of the core content (no blurred/black padding).
    crop_w = crop_h = crop_x = crop_y = 0
    if src_w > 0 and src_h > 0:
        target_ratio = 9 / 16
        if src_w / src_h >= target_ratio:
            crop_h = src_h
            crop_w = int(src_h * target_ratio)
            crop_x = max(0, (src_w - crop_w) // 2)
            crop_y = 0
        else:
            crop_w = src_w
            crop_h = int(src_w / target_ratio)
            crop_x = 0
            crop_y = max(0, (src_h - crop_h) // 2)
    main_crop_filter = (
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale={width}:{height},setsar=1,fps=30"
    ) if crop_w > 0 and crop_h > 0 else crop_filter

    facecam_geometry: tuple[int, int, int, int] | None = None
    if use_streamer and src_w > 0 and src_h > 0:
        try:
            parts = [float(part) for part in settings.clip_facecam_crop.split(",")]
        except ValueError:
            parts = []
        if len(parts) == 4:
            x1, y1, x2, y2 = [min(1.0, max(0.0, part)) for part in parts]
            fx = int(src_w * x1)
            fy = int(src_h * y1)
            fw = int(src_w * (x2 - x1))
            fh = int(src_h * (y2 - y1))
            if fw > 10 and fh > 10 and fx + fw <= src_w and fy + fh <= src_h:
                facecam_geometry = (fx, fy, fw, fh)
    if use_streamer and (facecam_geometry is None or crop_w <= 0):
        use_streamer = False
        use_fit = False

    def _fit_filter_complex(include_title: bool, include_subtitles: bool) -> str:
        chain = [
            "[0:v]split=2[bg][fg]",
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:2[bg2]",
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2]",
            "[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[base]",
        ]
        last = "base"
        if include_subtitles and subtitle_filter:
            chain.append(f"[{last}]{subtitle_filter}[sub]")
            last = "sub"
        if include_title and title_filter:
            chain.append(f"[{last}]{title_filter}[v]")
            last = "v"
        if last != "v":
            chain.append(f"[{last}]null[v]")
        return ";".join(chain)

    def _streamer_filter_complex(include_title: bool, include_subtitles: bool) -> str:
        assert facecam_geometry is not None
        fx, fy, fw, fh = facecam_geometry
        facecam_width = max(80, int(settings.clip_facecam_width))
        facecam_height = max(60, int(round(fh * facecam_width / fw)))
        if facecam_height % 2:
            facecam_height += 1
        margin = max(8, int(settings.clip_facecam_margin))
        chain = [
            f"[0:v]{main_crop_filter}[base]",
            f"[0:v]crop={fw}:{fh}:{fx}:{fy},"
            f"scale={facecam_width}:{facecam_height},"
            f"pad={facecam_width + 8}:{facecam_height + 8}:4:4:white[fc]",
            f"[base][fc]overlay=W-w-{margin}:{margin}[composed]",
        ]
        last = "composed"
        if include_subtitles and subtitle_filter:
            chain.append(f"[{last}]{subtitle_filter}[sub]")
            last = "sub"
        if include_title and title_filter:
            chain.append(f"[{last}]{title_filter}[v]")
            last = "v"
        if last != "v":
            chain.append(f"[{last}]null[v]")
        return ";".join(chain)

    if use_streamer:
        command = [
            *input_args,
            "-filter_complex",
            _streamer_filter_complex(True, True),
            "-map",
            "[v]",
        ]
        if has_audio:
            command += ["-map", "0:a?"]
        command += codec_args + audio_args + tail
    elif use_fit:
        command = [
            *input_args,
            "-filter_complex",
            _fit_filter_complex(True, True),
            "-map",
            "[v]",
        ]
        if has_audio:
            command += ["-map", "0:a?"]
        command += codec_args + audio_args + tail
    else:
        command = [
            *input_args,
            "-vf",
            ",".join(filters),
            *codec_args,
            *audio_args,
            *tail,
        ]

    result = _run(command, timeout=settings.clip_render_timeout)
    if result.returncode != 0:
        # Fonts/subtitle filters are host-dependent; retry first with the
        # full-frame crop and cosmetics, then with a clean crop if needed.
        if use_streamer:
            cosmetic = ",".join(
                [main_crop_filter]
                + [part for part in (title_filter, subtitle_filter) if part]
            )
            fallback = [
                *input_args,
                "-vf",
                cosmetic,
                *codec_args,
                *audio_args,
                *tail,
            ]
        elif use_fit:
            fallback_filter = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30"
            )
            fallback = [
                *input_args,
                "-vf",
                fallback_filter,
                *codec_args,
                *audio_args,
                *tail,
            ]
        else:
            fallback = [
                *input_args,
                "-vf",
                crop_filter,
                *codec_args,
                *audio_args,
                *tail,
            ]
        result = _run(fallback, timeout=settings.clip_render_timeout)
        if result.returncode != 0 and use_streamer:
            plain = [
                *input_args,
                "-vf",
                main_crop_filter,
                *codec_args,
                *audio_args,
                *tail,
            ]
            result = _run(plain, timeout=settings.clip_render_timeout)
    if result.returncode != 0 or not output_path.is_file():
        error = (result.stderr or "ffmpeg render failed")[-1500:]
        raise PipelineError(f"clip render failed: {error}")
    probe = probe_video(output_path)
    return {
        "path": str(output_path),
        "probe": probe,
        "bytes": output_path.stat().st_size,
        "srt": str(srt_path) if srt_path else None,
    }


# ---------------------------------------------------------------------- stage
class ClipperStage:
    def __init__(self, settings: PipelineSettings, db: PipelineDB) -> None:
        self.settings = settings
        self.db = db

    def require_rights(self) -> None:
        if not self.settings.rights_ack:
            raise PipelineError(
                "Clip mode downloads and republishes third-party YouTube footage. "
                "Only use videos you own or have permission to reuse. Confirm with "
                "`--rights-ack` or set PIPELINE_RIGHTS_ACK=true, then retry."
            )

    def clip_url(
        self,
        url: str,
        *,
        count: int | None = None,
        start: float | None = None,
        end: float | None = None,
        link_id: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_rights()
        count = max(1, int(count or self.settings.clip_count))
        if link_id is not None:
            link = self.db.get_link(link_id)
            if not link:
                raise PipelineError(f"link {link_id} not found")
        else:
            link_id, _created = self.db.add_link(
                {"url": url, "title": url, "query": "clip"}
            )
            link = self.db.get_link(link_id)
        if not link:
            raise PipelineError("could not create or find the source link")
        return self.clip_link(
            link,
            count=count,
            start=start,
            end=end,
            run_id=run_id,
        )

    def clip_link(
        self,
        link: dict[str, Any],
        *,
        count: int,
        start: float | None = None,
        end: float | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_rights()
        link_id = int(link["id"])
        url = str(link.get("url") or "").strip()
        if not url:
            raise PipelineError("source link has no URL")
        stats = {"links": 1, "clips": 0, "ready": 0, "failed": 0, "skipped": 0}
        self.db.update_link(link_id, status="generating", error=None)
        try:
            info = fetch_info(url, self.settings)
            duration = float(info.get("duration") or 0)
            if duration <= 0:
                raise PipelineError("source duration could not be determined")
            if duration > self.settings.clip_max_source_seconds:
                raise PipelineError(
                    f"source is {duration / 60:.0f} min; the configured maximum is "
                    f"{self.settings.clip_max_source_seconds / 60:.0f} min"
                )
            title = str(info.get("title") or link.get("title") or url)
            channel = str(info.get("channel") or info.get("uploader") or "")
            self.db.update_link(
                link_id,
                title=title,
                channel=channel,
                duration=str(int(duration)),
            )
            workdir = self.settings.sources_dir / safe_stem(
                str(info.get("id") or link_id), "source", 40
            )
            # Short sources are downloaded once and reused for both local
            # Whisper transcription and rendering. Long streams use caption
            # selection and section downloads to avoid multi-GB downloads.
            full_source: Path | None = None
            if duration <= self.settings.clip_max_full_download_seconds:
                full_source = download_full(url, info, workdir, self.settings)
            subtitle_path = download_subtitles(
                url, info, workdir, self.settings
            )
            segments = parse_vtt(subtitle_path) if subtitle_path else []
            if not segments and full_source is not None:
                segments = transcribe_local(full_source, workdir, self.settings)
            segments = [
                Segment(
                    start=segment.start,
                    end=segment.end,
                    text=apply_caption_fixes(segment.text, self.settings),
                )
                for segment in segments
            ]
            if start is not None and end is not None and end > start:
                windows = [
                    ClipWindow(
                        start=max(0.0, float(start)),
                        end=min(duration, float(end)),
                        score=1.0,
                        hook=_hook(
                            _window_text(segments, start, end) or title,
                            title,
                        ),
                        reason="operator-specified window",
                    )
                ]
            else:
                windows = select_windows(
                    segments,
                    duration,
                    count=count,
                    min_seconds=self.settings.clip_min_seconds,
                    max_seconds=self.settings.clip_max_seconds,
                    target_seconds=self.settings.clip_target_seconds,
                    fallback_title=title,
                )
            if not windows:
                raise PipelineError("no clip windows could be selected")
            LOGGER.info(
                "clipping %s (%s): %s window(s), captions=%s",
                title,
                url,
                len(windows),
                bool(segments),
            )
            for index, window in enumerate(windows):
                generation_id = self.db.create_generation(
                    link_id,
                    index,
                    direction=(
                        f"clip {url} {window.start:.1f}-{window.end:.1f}"
                    ),
                    status="generating",
                )
                current = self.db.get_generation(generation_id) or {}
                title_value = self._clip_title(window, title, index)
                self.db.update_generation(
                    generation_id,
                    attempts=int(current.get("attempts") or 0) + 1,
                    title=title_value,
                    direction=f"clip {url} {window.start:.1f}-{window.end:.1f}",
                )
                # Stable filename: re-running a generation overwrites its clip
                # instead of leaving stale duplicates in the videos folder.
                output = self.settings.videos_dir / f"clip{generation_id:05d}.mp4"
                try:
                    if full_source is not None:
                        rendered = render_clip(
                            full_source,
                            window.start,
                            window.end,
                            output,
                            title=title_value,
                            segments=segments,
                            window_start=window.start,
                            window_end=window.end,
                            settings=self.settings,
                        )
                    else:
                        section = download_section(
                            url,
                            info,
                            workdir,
                            window.start,
                            window.end,
                            index,
                            self.settings,
                        )
                        rendered = render_clip(
                            section,
                            0.0,
                            window.duration,
                            output,
                            title=title_value,
                            segments=segments,
                            window_start=window.start,
                            window_end=window.end,
                            settings=self.settings,
                        )
                    stats["clips"] += 1
                    if self._accept(rendered, generation_id, window):
                        stats["ready"] += 1
                    else:
                        stats["failed"] += 1
                except PipelineError as error:
                    self.db.update_generation(
                        generation_id, status="failed", error=str(error)[:1200]
                    )
                    stats["failed"] += 1
                    LOGGER.warning("clip render failed: %s", error)
            if stats["ready"]:
                self.db.update_link(link_id, status="generated", error=None)
            elif stats["failed"]:
                self.db.update_link(link_id, status="failed", error="all clips failed")
            else:
                self.db.update_link(link_id, status="skipped", error="no clips")
        except PipelineError as error:
            self.db.update_link(link_id, status="failed", error=str(error)[:1200])
            self.db.log_event("clip.failed", str(error), link_id, run_id)
            raise
        self.db.log_event(
            "clip.stage",
            f"link {link_id}: {stats}",
            link_id,
            run_id,
            payload=stats,
        )
        return stats

    def _clip_title(self, window: ClipWindow, source_title: str, index: int) -> str:
        hook = _clean_text(window.hook) or source_title
        if len(hook) > 70:
            hook = hook[:69].rsplit(" ", 1)[0]
        prefix = self.settings.clip_title_prefix.strip()
        if prefix and prefix.lower() not in hook.lower():
            return f"{hook} | {prefix}"[:100]
        return (hook or f"{source_title} - clip {index + 1}")[:100]

    def _accept(
        self, rendered: dict[str, Any], generation_id: int, window: ClipWindow
    ) -> bool:
        path = str(rendered.get("path") or "")
        probe = rendered.get("probe") or {}
        if not looks_like_video(path):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error="rendered file is not a video container",
            )
            return False
        if probe.get("ok") and not is_vertical(probe):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error=f"clip is not vertical: {probe.get('width')}x{probe.get('height')}",
            )
            return False
        if not probe.get("ok") and "ffprobe not installed" not in str(
            probe.get("error") or ""
        ):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error=f"ffprobe rejected the clip: {probe.get('error')}",
            )
            return False
        self.db.update_generation(
            generation_id,
            status="ready",
            host_path=path,
            duration_seconds=probe.get("duration_seconds"),
            width=probe.get("width"),
            height=probe.get("height"),
            error=None,
        )
        self.db.enqueue_posts(generation_id, self.settings.platforms)
        return True

    def generate(
        self,
        *,
        limit: int | None = None,
        count: int | None = None,
        link_id: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_rights()
        count = max(1, int(count or self.settings.clip_count))
        if link_id is not None:
            link = self.db.get_link(link_id)
            if not link:
                raise PipelineError(f"link {link_id} not found")
            links = [link]
        else:
            links = self.db.claim_links(int(limit or self.settings.links_per_cycle))
        totals = {"links": 0, "clips": 0, "ready": 0, "failed": 0, "skipped": 0}
        for link in links:
            totals["links"] += 1
            try:
                result = self.clip_link(
                    link, count=count, run_id=run_id
                )
                for key in ("clips", "ready", "failed", "skipped"):
                    totals[key] += int(result.get(key) or 0)
            except PipelineError:
                totals["failed"] += 1
                raise
        return totals
