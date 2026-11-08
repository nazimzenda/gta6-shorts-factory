from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.errors import Conflict, MediaToolUnavailable, NotFound, PolicyError, RightsError
from app.policy import require_local_processing, valid_rights
from app.storage import Store

HOOK_KEYWORDS = {
    "wow",
    "no way",
    "insane",
    "secret",
    "found",
    "first",
    "best",
    "worst",
    "funny",
    "fail",
    "reaction",
    "actually",
    "watch",
    "look",
    "how",
    "why",
    "new",
    "gta",
    "gameplay",
    "mission",
    "police",
    "chase",
    "explosion",
    "glitch",
    "bug",
    "discover",
    "unbelievable",
}

STYLES: dict[str, dict[str, str]] = {
    "reaction_first": {
        "title": "{hook} (reaction)",
        "script": "Open on the reaction, then explain what happened and why it matters.",
        "pacing": "fast",
        "caption_prefix": "Wait for it... ",
    },
    "story_first": {
        "title": "{hook} - the full story",
        "script": "Establish the setup, build tension, and land the payoff with attribution.",
        "pacing": "measured",
        "caption_prefix": "The story behind this moment: ",
    },
    "funny_failure": {
        "title": "{hook} but it goes wrong",
        "script": "Lead with the failure, keep the joke clean, and avoid mocking the creator.",
        "pacing": "snappy",
        "caption_prefix": "This did not go to plan: ",
    },
    "discovery": {
        "title": "I found {hook}",
        "script": "Frame the discovery, add context, and separate fact from speculation.",
        "pacing": "clear",
        "caption_prefix": "Here is what I found: ",
    },
    "fast_caption": {
        "title": "{hook} in 30 seconds",
        "script": "Caption-led cut with one idea per beat and a strong final line.",
        "pacing": "rapid",
        "caption_prefix": "In 30 seconds: ",
    },
}

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)


@lru_cache(maxsize=1)
def media_tools() -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    versions: dict[str, str] = {}
    for name, binary in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not binary:
            continue
        try:
            result = subprocess.run(
                [binary, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            versions[name] = (result.stdout.splitlines() or [""])[0][:160]
        except (OSError, subprocess.SubprocessError):
            versions[name] = "installed (version unavailable)"
    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "available": bool(ffmpeg and ffprobe),
        "versions": versions,
    }


def _font_path() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise PolicyError(f"media command timed out after {timeout}s") from error
    except OSError as error:
        raise MediaToolUnavailable(f"media command could not start: {error}") from error


def probe_media(path: str | Path) -> dict[str, Any]:
    """Return technical metadata, with an explicit fallback when ffprobe is absent."""
    media_path = Path(path)
    info: dict[str, Any] = {
        "available": False,
        "path": str(media_path),
        "exists": media_path.is_file(),
        "size_bytes": media_path.stat().st_size if media_path.is_file() else 0,
        "duration": None,
        "width": None,
        "height": None,
        "has_audio": False,
        "has_video": False,
        "video_codec": None,
        "audio_codec": None,
        "fps": None,
        "format": None,
    }
    if not media_path.is_file():
        return info
    tools = media_tools()
    if not tools["ffprobe"]:
        return info
    result = _run(
        [
            str(tools["ffprobe"]),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        info["error"] = (result.stderr or "ffprobe failed")[-600:]
        return info
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        info["error"] = "ffprobe returned invalid JSON"
        return info

    streams = payload.get("streams", [])
    format_info = payload.get("format", {})
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = format_info.get("duration") or (video or {}).get("duration")
    try:
        info["duration"] = round(float(duration), 3) if duration is not None else None
    except (TypeError, ValueError):
        info["duration"] = None
    if video:
        info["has_video"] = True
        info["width"] = int(video.get("width") or 0) or None
        info["height"] = int(video.get("height") or 0) or None
        info["video_codec"] = video.get("codec_name")
        frame_rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
        if frame_rate and "/" in str(frame_rate):
            numerator, denominator = str(frame_rate).split("/", 1)
            try:
                info["fps"] = round(float(numerator) / float(denominator), 3)
            except (ValueError, ZeroDivisionError):
                info["fps"] = None
    if audio:
        info["has_audio"] = True
        info["audio_codec"] = audio.get("codec_name")
    info["format"] = format_info.get("format_name")
    info["available"] = True
    return info


def transcribe_media(path: str | Path) -> dict[str, Any]:
    """Use a local Whisper runtime when installed. Never calls a remote API."""
    media_path = str(path)
    try:
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(settings.whisper_model, device="auto", compute_type="auto")
        segments, info = model.transcribe(media_path, vad_filter=True)
        rows = [
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
            }
            for segment in segments
            if segment.text.strip()
        ]
        return {
            "status": "ready",
            "model": f"faster-whisper:{settings.whisper_model}",
            "language": getattr(info, "language", "en") or "en",
            "confidence": None,
            "segments": rows,
        }
    except ImportError:
        pass
    except Exception as error:  # pragma: no cover - depends on optional runtime
        return {
            "status": "error",
            "model": "faster-whisper",
            "language": "en",
            "confidence": None,
            "segments": [],
            "message": f"local transcription failed: {error}",
        }

    try:
        import whisper  # type: ignore

        model = whisper.load_model(settings.whisper_model)
        result = model.transcribe(media_path)
        rows = [
            {
                "start": round(float(segment.get("start", 0)), 3),
                "end": round(float(segment.get("end", 0)), 3),
                "text": str(segment.get("text", "")).strip(),
            }
            for segment in result.get("segments", [])
            if str(segment.get("text", "")).strip()
        ]
        return {
            "status": "ready",
            "model": f"whisper:{settings.whisper_model}",
            "language": result.get("language", "en"),
            "confidence": None,
            "segments": rows,
        }
    except ImportError:
        return {
            "status": "unavailable",
            "model": None,
            "language": "en",
            "confidence": None,
            "segments": [],
            "message": "Install faster-whisper or whisper to enable local transcription; "
            "you can also attach a manual transcript.",
        }
    except Exception as error:  # pragma: no cover - depends on optional runtime
        return {
            "status": "error",
            "model": "whisper",
            "language": "en",
            "confidence": None,
            "segments": [],
            "message": f"local transcription failed: {error}",
        }


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
        .replace("\n", " ")
    )


class MediaPipeline:
    def __init__(self, repository: Store) -> None:
        self.repository = repository

    # ------------------------------------------------------------------ ingest
    def register_asset(
        self,
        path: str | Path,
        *,
        owner: str | None = None,
        source_url: str | None = None,
        rights_id: str | None = None,
        copy_into_uploads: bool = False,
    ) -> dict[str, Any]:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise NotFound("source file does not exist")
        size = source.stat().st_size
        if size > settings.max_upload_mb * 1024 * 1024:
            raise PolicyError(f"source exceeds the {settings.max_upload_mb} MB upload limit")

        digest = self._hash_file(source)
        existing = self.repository.one(
            "SELECT * FROM source_assets WHERE sha256 = ?", (digest,), "source_assets"
        )
        if existing:
            raise Conflict(f"source already ingested as {existing['id']}")

        if rights_id:
            rights = self.repository.one(
                "SELECT * FROM rights_records WHERE id = ?", (rights_id,), "rights_records"
            )
            if not rights:
                raise RightsError("asset requires approved commercial rights")
            if rights["status"] != "approved" or not rights["commercial_use"]:
                raise RightsError("asset requires approved commercial rights")

        stored_path = source
        if copy_into_uploads:
            stored_path = settings.upload_dir / f"{digest[:12]}-{source.name}"
            if not stored_path.exists():
                shutil.copy2(source, stored_path)

        metadata = probe_media(stored_path)
        asset_id = str(uuid.uuid4())
        status = "rights_approved" if rights_id else "pending_rights"
        self.repository.insert(
            "source_assets",
            {
                "id": asset_id,
                "uri": stored_path.resolve().as_uri(),
                "path": str(stored_path.resolve()),
                "filename": source.name,
                "sha256": digest,
                "owner": owner or "founder",
                "source_url": source_url,
                "size_bytes": size,
                "duration": metadata.get("duration"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "status": status,
                "metadata": metadata,
            },
        )
        self.repository.insert(
            "media_assets",
            {
                "id": str(uuid.uuid4()),
                "source_asset_id": asset_id,
                "kind": "source",
                "uri": str(stored_path.resolve()),
                "duration": metadata.get("duration"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "metadata": metadata,
            },
        )
        if rights_id:
            self.repository.execute(
                "UPDATE rights_records SET source_asset_id = ? WHERE id = ?",
                (asset_id, rights_id),
            )
        self.repository.audit(
            "production",
            "source_asset_ingested",
            asset_id,
            {"sha256": digest, "path": str(stored_path), "rights_id": rights_id},
        )
        return self.get_asset(asset_id)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self.repository.one(
            "SELECT * FROM source_assets WHERE id = ?", (asset_id,), "source_assets"
        )
        if not asset:
            raise NotFound("source asset not found")
        asset["rights"] = self.repository.many(
            "SELECT * FROM rights_records WHERE source_asset_id = ? ORDER BY created_at DESC",
            (asset_id,),
            "rights_records",
        )
        asset["candidate_count"] = self.repository.count(
            "highlight_candidates", "media_asset_id IN (SELECT id FROM media_assets WHERE source_asset_id = ?)", (asset_id,)
        )
        return asset

    def _source_media_asset(self, asset_id: str) -> dict[str, Any]:
        media = self.repository.one(
            "SELECT * FROM media_assets WHERE source_asset_id = ? AND kind = 'source' "
            "ORDER BY created_at ASC LIMIT 1",
            (asset_id,),
            "media_assets",
        )
        if not media:
            raise NotFound("source media asset not found; re-ingest the file")
        return media

    # ---------------------------------------------------------------- analysis
    def analyze_asset(self, asset_id: str, refresh: bool = False) -> dict[str, Any]:
        require_local_processing()
        asset = self.repository.one(
            "SELECT * FROM source_assets WHERE id = ?", (asset_id,), "source_assets"
        )
        if not asset:
            raise NotFound("source asset not found")
        rights = valid_rights(self.repository, asset_id)
        media = self._source_media_asset(asset_id)

        media_path = Path(asset.get("path") or "")
        if not media_path.is_file():
            raise NotFound("source file is no longer available on disk")
        metadata = probe_media(media_path)
        duration = float(metadata.get("duration") or asset.get("duration") or 0)
        if duration <= 0:
            raise PolicyError("source duration could not be determined; install ffprobe")
        self.repository.execute(
            "UPDATE source_assets SET duration = ?, width = ?, height = ?, metadata = ?, "
            "status = 'analyzed' WHERE id = ?",
            (
                duration,
                metadata.get("width"),
                metadata.get("height"),
                json.dumps(metadata, sort_keys=True),
                asset_id,
            ),
        )

        transcript = self.repository.one(
            "SELECT * FROM transcripts WHERE media_asset_id = ?",
            (media["id"],),
            "transcripts",
        )
        if not transcript:
            result = transcribe_media(media_path)
            transcript = self.repository.insert(
                "transcripts",
                {
                    "id": str(uuid.uuid4()),
                    "media_asset_id": media["id"],
                    "language": result.get("language", "en"),
                    "segments": result.get("segments", []),
                    "model": result.get("model"),
                    "confidence": result.get("confidence"),
                    "status": result.get("status", "unavailable"),
                },
            )
            if result.get("message"):
                transcript["message"] = result["message"]

        existing_candidates = self.repository.many(
            "SELECT * FROM highlight_candidates WHERE media_asset_id = ? ORDER BY score DESC",
            (media["id"],),
            "highlight_candidates",
        )
        if refresh and existing_candidates:
            variant_count = self.repository.count(
                "video_variants",
                "candidate_id IN (SELECT id FROM highlight_candidates WHERE media_asset_id = ?)",
                (media["id"],),
            )
            if variant_count == 0:
                self.repository.execute(
                    "DELETE FROM highlight_candidates WHERE media_asset_id = ?", (media["id"],)
                )
                existing_candidates = []

        if not existing_candidates:
            candidates = self._build_candidates(media["id"], duration, transcript)
            for candidate in candidates:
                self.repository.insert("highlight_candidates", candidate)
            existing_candidates = self.repository.many(
                "SELECT * FROM highlight_candidates WHERE media_asset_id = ? ORDER BY score DESC",
                (media["id"],),
                "highlight_candidates",
            )

        self.repository.audit(
            "production",
            "asset_analyzed",
            asset_id,
            {
                "duration": duration,
                "candidates": len(existing_candidates),
                "transcript_status": transcript.get("status"),
                "rights_id": rights["id"],
            },
        )
        return {
            "asset": self.get_asset(asset_id),
            "media_asset": media,
            "transcript": transcript,
            "candidates": existing_candidates,
            "media_tools": media_tools(),
        }

    def _build_candidates(
        self, media_asset_id: str, duration: float, transcript: dict[str, Any]
    ) -> list[dict[str, Any]]:
        segments = transcript.get("segments") or []
        candidates: list[dict[str, Any]] = []
        if segments:
            scored: list[tuple[float, dict[str, Any]]] = []
            for segment in segments:
                text = str(segment.get("text", "")).strip()
                if not text:
                    continue
                lower = text.lower()
                hits = sum(1 for keyword in HOOK_KEYWORDS if keyword in lower)
                score = min(0.98, 0.42 + hits * 0.08 + min(0.22, len(text) / 420))
                scored.append((score, segment))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            selected: list[tuple[float, float]] = []
            for score, segment in scored:
                start = max(0.0, float(segment.get("start", 0)) - 1.0)
                end = min(duration, float(segment.get("end", start + 5)) + 2.0)
                if end - start < 3:
                    end = min(duration, start + 3)
                if end - start > settings.max_clip_seconds:
                    end = start + settings.max_clip_seconds
                if any(start < existing_end and end > existing_start for existing_start, existing_end in selected):
                    continue
                selected.append((start, end))
                candidate_id = str(uuid.uuid4())
                text = str(segment.get("text", "")).strip()
                candidates.append(
                    {
                        "id": candidate_id,
                        "media_asset_id": media_asset_id,
                        "start_ms": int(round(start * 1000)),
                        "end_ms": int(round(end * 1000)),
                        "score": round(score, 3),
                        "reason": "transcript keyword match and speech-density heuristic",
                        "hook": self._clip_text(text, 90),
                        "status": "proposed",
                    }
                )
                if len(candidates) >= 5:
                    break
        if candidates:
            return candidates

        if duration <= 45:
            windows = [(0.0, duration)]
            scores = [0.55]
        else:
            length = min(32.0, max(18.0, duration / 4))
            starts = [0.0, max(0.0, duration * 0.34), max(0.0, duration * 0.67)]
            windows = []
            for start in starts:
                end = min(duration, start + length)
                if end - start >= 3:
                    windows.append((start, end))
            scores = [0.58, 0.52, 0.46][: len(windows)]
        for index, (start, end) in enumerate(windows):
            candidates.append(
                {
                    "id": str(uuid.uuid4()),
                    "media_asset_id": media_asset_id,
                    "start_ms": int(round(start * 1000)),
                    "end_ms": int(round(end * 1000)),
                    "score": scores[index],
                    "reason": "duration heuristic; transcript unavailable",
                    "hook": f"High-energy window {index + 1}",
                    "status": "proposed",
                }
            )
        return candidates

    @staticmethod
    def _clip_text(text: str, limit: int) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"

    def attach_transcript(
        self, asset_id: str, text: str | None, segments: list[dict[str, Any]] | None, language: str = "en"
    ) -> dict[str, Any]:
        asset = self.repository.one(
            "SELECT * FROM source_assets WHERE id = ?", (asset_id,), "source_assets"
        )
        if not asset:
            raise NotFound("source asset not found")
        media = self._source_media_asset(asset_id)
        duration = float(asset.get("duration") or 0)
        if segments is None:
            segments = self._text_to_segments(text or "", duration)
        cleaned = []
        for segment in segments:
            start = max(0.0, float(segment.get("start", 0)))
            end = max(start + 0.5, float(segment.get("end", start + 2)))
            text_value = str(segment.get("text", "")).strip()
            if text_value:
                cleaned.append(
                    {"start": round(start, 3), "end": round(end, 3), "text": text_value}
                )
        if not cleaned:
            raise PolicyError("transcript must contain at least one non-empty segment")
        existing = self.repository.one(
            "SELECT * FROM transcripts WHERE media_asset_id = ?", (media["id"],), "transcripts"
        )
        if existing:
            transcript = self.repository.update(
                "transcripts",
                existing["id"],
                {
                    "segments": cleaned,
                    "language": language,
                    "model": "manual",
                    "confidence": 1.0,
                    "status": "ready",
                },
            )
        else:
            transcript = self.repository.insert(
                "transcripts",
                {
                    "id": str(uuid.uuid4()),
                    "media_asset_id": media["id"],
                    "language": language,
                    "segments": cleaned,
                    "model": "manual",
                    "confidence": 1.0,
                    "status": "ready",
                },
            )
        self.repository.audit(
            "production", "transcript_attached", asset_id, {"segments": len(cleaned)}
        )
        return transcript

    @staticmethod
    def _text_to_segments(text: str, duration: float) -> list[dict[str, Any]]:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if not sentences:
            return []
        total_chars = sum(len(sentence) for sentence in sentences) or 1
        cursor = 0.0
        rows = []
        for sentence in sentences:
            span = max(1.0, duration * (len(sentence) / total_chars)) if duration else 2.0
            rows.append(
                {
                    "start": round(cursor, 3),
                    "end": round(min(duration, cursor + span) if duration else cursor + span, 3),
                    "text": sentence,
                }
            )
            cursor += span
        return rows

    # ---------------------------------------------------------------- variants
    def create_variants(
        self, candidate_id: str, styles: list[str] | None = None, force: bool = False
    ) -> list[dict[str, Any]]:
        candidate = self.repository.one(
            "SELECT * FROM highlight_candidates WHERE id = ?",
            (candidate_id,),
            "highlight_candidates",
        )
        if not candidate:
            raise NotFound("highlight candidate not found")
        media = self.repository.one(
            "SELECT * FROM media_assets WHERE id = ?", (candidate["media_asset_id"],), "media_assets"
        )
        if not media:
            raise NotFound("media asset not found")
        valid_rights(self.repository, media["source_asset_id"])
        existing = self.repository.many(
            "SELECT * FROM video_variants WHERE candidate_id = ? ORDER BY created_at ASC",
            (candidate_id,),
            "video_variants",
        )
        if existing and not force:
            return existing

        selected_styles = styles or list(STYLES)
        selected_styles = [style for style in selected_styles if style in STYLES]
        if not selected_styles:
            raise PolicyError("no supported creative styles were requested")
        hook = candidate.get("hook") or "Untitled moment"
        variants: list[dict[str, Any]] = []
        for style in selected_styles:
            definition = STYLES[style]
            title = definition["title"].format(hook=self._clip_text(hook, 70))
            caption = definition["caption_prefix"] + self._clip_text(hook, 110)
            variant = self.repository.insert(
                "video_variants",
                {
                    "id": str(uuid.uuid4()),
                    "candidate_id": candidate_id,
                    "style": style,
                    "title": title,
                    "script": definition["script"],
                    "caption_text": caption,
                    "status": "draft",
                },
            )
            variants.append(variant)
        self.repository.execute(
            "UPDATE highlight_candidates SET status = 'variants_created' WHERE id = ?",
            (candidate_id,),
        )
        self.repository.audit(
            "creative",
            "variants_created",
            candidate_id,
            {"styles": selected_styles, "count": len(variants)},
        )
        return variants

    def get_variant(self, variant_id: str) -> dict[str, Any]:
        variant = self.repository.one(
            "SELECT * FROM video_variants WHERE id = ?", (variant_id,), "video_variants"
        )
        if not variant:
            raise NotFound("video variant not found")
        candidate = self.repository.one(
            "SELECT * FROM highlight_candidates WHERE id = ?",
            (variant["candidate_id"],),
            "highlight_candidates",
        )
        media = None
        source = None
        if candidate:
            media = self.repository.one(
                "SELECT * FROM media_assets WHERE id = ?",
                (candidate["media_asset_id"],),
                "media_assets",
            )
            if media:
                source = self.repository.one(
                    "SELECT * FROM source_assets WHERE id = ?",
                    (media["source_asset_id"],),
                    "source_assets",
                )
        variant["candidate"] = candidate
        variant["media_asset"] = media
        variant["source_asset"] = source
        variant["approval"] = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'final_video' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (variant_id,),
            "approvals",
        )
        return variant

    # ------------------------------------------------------------------ render
    def render_variant(self, variant_id: str, force: bool = False) -> dict[str, Any]:
        require_local_processing()
        variant = self.repository.one(
            "SELECT * FROM video_variants WHERE id = ?", (variant_id,), "video_variants"
        )
        if not variant:
            raise NotFound("video variant not found")
        candidate = self.repository.one(
            "SELECT * FROM highlight_candidates WHERE id = ?",
            (variant["candidate_id"],),
            "highlight_candidates",
        )
        if not candidate:
            raise NotFound("highlight candidate not found")
        media = self.repository.one(
            "SELECT * FROM media_assets WHERE id = ?", (candidate["media_asset_id"],), "media_assets"
        )
        if not media:
            raise NotFound("media asset not found")
        source = self.repository.one(
            "SELECT * FROM source_assets WHERE id = ?",
            (media["source_asset_id"],),
            "source_assets",
        )
        if not source:
            raise NotFound("source asset not found")
        valid_rights(self.repository, source["id"])
        source_path = Path(source.get("path") or "")
        if not source_path.is_file():
            raise NotFound("source file is missing; re-ingest it before rendering")

        existing_render = variant.get("render_uri")
        if existing_render and Path(existing_render).is_file() and not force:
            return {
                "variant": variant,
                "render_job": self.repository.one(
                    "SELECT * FROM render_jobs WHERE variant_id = ? ORDER BY created_at DESC LIMIT 1",
                    (variant_id,),
                    "render_jobs",
                ),
                "reused": True,
            }

        job = self.repository.insert(
            "render_jobs",
            {
                "id": str(uuid.uuid4()),
                "variant_id": variant_id,
                "status": "running",
                "progress": 10,
                "started_at": None,
            },
        )
        self.repository.execute(
            "UPDATE render_jobs SET started_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],)
        )
        self.repository.execute(
            "UPDATE video_variants SET status = 'rendering', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (variant_id,),
        )
        tools = media_tools()
        if not tools["available"]:
            self.repository.update(
                "render_jobs",
                job["id"],
                {
                    "status": "failed",
                    "progress": 100,
                    "error": "ffmpeg and ffprobe are not installed",
                    "finished_at": None,
                },
            )
            self.repository.execute(
                "UPDATE render_jobs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job["id"],),
            )
            self.repository.update(
                "video_variants",
                variant_id,
                {"status": "render_blocked", "qc_status": "blocked"},
            )
            raise MediaToolUnavailable(
                "ffmpeg and ffprobe are required for rendering; install them and retry"
            )

        start = max(0.0, candidate["start_ms"] / 1000)
        duration = max(0.5, (candidate["end_ms"] - candidate["start_ms"]) / 1000)
        duration = min(duration, settings.max_clip_seconds)
        caption_path = self._write_caption(variant, candidate, media)
        output = settings.render_dir / f"{variant_id}-{variant['style']}.mp4"
        info = probe_media(source_path)
        has_audio = bool(info.get("has_audio"))

        base_filter = (
            f"scale={settings.render_width}:{settings.render_height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={settings.render_width}:{settings.render_height},setsar=1,fps=30"
        )
        caption_filter = ""
        font = _font_path()
        if font and variant.get("caption_text"):
            caption_filter = (
                ",drawtext="
                f"fontfile={font}:"
                f"text='{_escape_drawtext(self._clip_text(variant['caption_text'], 64))}':"
                "fontcolor=white:fontsize=54:line_spacing=10:"
                "box=1:boxcolor=black@0.55:boxborderw=18:"
                "x=(w-text_w)/2:y=h-520"
            )

        command_base = [
            str(tools["ffmpeg"]),
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source_path),
            "-vf",
            base_filter + caption_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
        ]
        if has_audio:
            command_base += ["-c:a", "aac", "-b:a", "128k"]
        else:
            command_base += ["-an"]
        command_base += ["-movflags", "+faststart", str(output)]

        self.repository.update("render_jobs", job["id"], {"progress": 35, "command": " ".join(command_base)})
        result = _run(command_base, timeout=240)
        if result.returncode != 0 and caption_filter:
            # Caption fonts and drawtext escaping are host-dependent. Retry a clean
            # vertical render and keep the sidecar caption file for the editor.
            fallback = [part for part in command_base]
            fallback[fallback.index("-vf") + 1] = base_filter
            result = _run(fallback, timeout=240)
            if result.returncode == 0:
                self.repository.audit(
                    "production",
                    "caption_burn_in_skipped",
                    variant_id,
                    {"reason": "drawtext failed; sidecar caption retained"},
                )
        if result.returncode != 0 or not output.is_file():
            error = (result.stderr or "ffmpeg render failed")[-1500:]
            self.repository.update(
                "render_jobs",
                job["id"],
                {"status": "failed", "progress": 100, "error": error},
            )
            self.repository.execute(
                "UPDATE render_jobs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],)
            )
            self.repository.update(
                "video_variants",
                variant_id,
                {
                    "status": "render_failed",
                    "render_uri": None,
                    "caption_uri": str(caption_path),
                },
            )
            self.repository.audit(
                "production", "render_failed", variant_id, {"error": error[-400:]}
            )
            raise PolicyError(f"render failed: {error[-400:]}")

        rendered = probe_media(output)
        self.repository.update(
            "render_jobs",
            job["id"],
            {
                "status": "completed",
                "progress": 100,
                "error": None,
            },
        )
        self.repository.execute(
            "UPDATE render_jobs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (job["id"],)
        )
        self.repository.update(
            "video_variants",
            variant_id,
            {
                "render_uri": str(output),
                "caption_uri": str(caption_path),
                "status": "rendered",
                "qc_status": "pending",
            },
        )
        self.repository.insert(
            "cost_events",
            {
                "id": str(uuid.uuid4()),
                "provider": "local",
                "category": "render",
                "amount": 0.0,
                "currency": "USD",
                "job_id": job["id"],
                "note": f"local render {rendered.get('duration')}s",
            },
        )
        self.repository.audit(
            "production",
            "render_completed",
            variant_id,
            {
                "render_job_id": job["id"],
                "duration": rendered.get("duration"),
                "width": rendered.get("width"),
                "height": rendered.get("height"),
                "captioned": bool(caption_filter),
            },
        )
        return {
            "variant": self.get_variant(variant_id),
            "render_job": self.repository.one(
                "SELECT * FROM render_jobs WHERE id = ?", (job["id"],), "render_jobs"
            ),
            "reused": False,
        }

    def _write_caption(
        self, variant: dict[str, Any], candidate: dict[str, Any], media: dict[str, Any]
    ) -> Path:
        transcript = self.repository.one(
            "SELECT * FROM transcripts WHERE media_asset_id = ?",
            (media["id"],),
            "transcripts",
        )
        clip_start = candidate["start_ms"] / 1000
        clip_end = candidate["end_ms"] / 1000
        rows: list[tuple[float, float, str]] = []
        if transcript and transcript.get("status") == "ready":
            for segment in transcript.get("segments") or []:
                start = float(segment.get("start", 0))
                end = float(segment.get("end", start + 1))
                if end <= clip_start or start >= clip_end:
                    continue
                rows.append(
                    (
                        max(0.0, start - clip_start),
                        min(clip_end - clip_start, end - clip_start),
                        str(segment.get("text", "")).strip(),
                    )
                )
        if not rows:
            text = variant.get("caption_text") or variant.get("title") or "Rights-cleared short"
            rows = [(0.0, max(1.0, clip_end - clip_start), text)]
        lines = []
        for index, (start, end, text) in enumerate(rows, start=1):
            lines.extend(
                [
                    str(index),
                    f"{_srt_time(start)} --> {_srt_time(max(start + 0.5, end))}",
                    text,
                    "",
                ]
            )
        path = settings.caption_dir / f"{variant['id']}.srt"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ---------------------------------------------------------------------- QC
    def qc_variant(self, variant_id: str) -> dict[str, Any]:
        variant = self.repository.one(
            "SELECT * FROM video_variants WHERE id = ?", (variant_id,), "video_variants"
        )
        if not variant:
            raise NotFound("video variant not found")
        candidate = self.repository.one(
            "SELECT * FROM highlight_candidates WHERE id = ?",
            (variant["candidate_id"],),
            "highlight_candidates",
        )
        checks: dict[str, dict[str, Any]] = {}
        render_path = Path(variant.get("render_uri") or "")
        checks["file_exists"] = {
            "passed": bool(render_path.is_file()),
            "detail": str(render_path),
        }
        info = probe_media(render_path) if render_path.is_file() else {}
        checks["decodes"] = {
            "passed": bool(info.get("available") and info.get("has_video")),
            "detail": info.get("video_codec"),
        }
        duration = info.get("duration") or 0
        checks["duration"] = {
            "passed": settings.min_clip_seconds <= duration <= settings.max_clip_seconds,
            "detail": f"{duration}s (allowed {settings.min_clip_seconds}-{settings.max_clip_seconds}s)",
        }
        width, height = info.get("width"), info.get("height")
        checks["vertical"] = {
            "passed": bool(
                width
                and height
                and width == settings.render_width
                and height == settings.render_height
            ),
            "detail": f"{width}x{height}",
        }
        checks["audio"] = {
            "passed": bool(info.get("has_audio")),
            "detail": info.get("audio_codec"),
        }
        caption_path = Path(variant.get("caption_uri") or "")
        checks["captions"] = {
            "passed": bool(caption_path.is_file()),
            "detail": str(caption_path),
        }
        rights_ok = True
        rights_detail = ""
        try:
            if candidate:
                media = self.repository.one(
                    "SELECT * FROM media_assets WHERE id = ?",
                    (candidate["media_asset_id"],),
                    "media_assets",
                )
                if media:
                    valid_rights(self.repository, media["source_asset_id"])
        except RightsError as error:
            rights_ok = False
            rights_detail = str(error)
        checks["rights"] = {"passed": rights_ok, "detail": rights_detail}
        checks["file_size"] = {
            "passed": render_path.is_file() and render_path.stat().st_size > 10_000,
            "detail": render_path.stat().st_size if render_path.is_file() else 0,
        }
        passed = all(check["passed"] for check in checks.values())
        report = {
            "passed": passed,
            "checks": checks,
            "checked_at": None,
            "media": {
                key: info.get(key)
                for key in ("duration", "width", "height", "audio_codec", "video_codec")
            },
        }
        qc_status = "passed" if passed else "failed"
        status = "qc_passed" if passed else "qc_failed"
        self.repository.update(
            "video_variants",
            variant_id,
            {
                "qc_status": qc_status,
                "qc_report": report,
                "status": status,
            },
        )
        self.repository.audit(
            "production",
            "qc_completed",
            variant_id,
            {"passed": passed, "checks": {key: value["passed"] for key, value in checks.items()}},
        )
        return self.get_variant(variant_id)

    # ------------------------------------------------------------------ review
    def submit_for_review(self, variant_id: str) -> dict[str, Any]:
        variant = self.get_variant(variant_id)
        if variant["qc_status"] != "passed":
            raise PolicyError("variant must pass quality control before founder review")
        existing = variant.get("approval")
        if existing and existing["status"] in {"pending", "approved"}:
            return {"variant": variant, "approval": existing, "reused": True}
        import uuid as _uuid

        approval_id = str(_uuid.uuid4())
        self.repository.insert(
            "approvals",
            {
                "id": approval_id,
                "type": "final_video",
                "subject_type": "video_variant",
                "subject_id": variant_id,
                "requested_by": "production",
                "status": "pending",
                "reason": f"Review {variant['style']} draft: {variant['title']}",
            },
        )
        self.repository.update(
            "video_variants",
            variant_id,
            {"status": "in_review"},
        )
        self.repository.execute(
            "UPDATE video_variants SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (variant_id,),
        )
        self.repository.audit(
            "production",
            "final_video_submitted",
            variant_id,
            {"approval_id": approval_id},
            approval_id,
        )
        return {
            "variant": self.get_variant(variant_id),
            "approval": self.repository.one(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,), "approvals"
            ),
            "reused": False,
        }
