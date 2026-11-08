"""Small media helpers used by the pipeline host."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def safe_stem(value: str, fallback: str = "short", limit: int = 60) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip()).strip("-._")
    cleaned = cleaned[:limit].strip("-._")
    return cleaned or fallback


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def looks_like_video(path: str | Path) -> bool:
    """Cheap container sniff so an HTML error page is never queued as video."""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return False
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # Matroska / WebM
        return True
    if len(head) >= 12 and head[4:8] == b"ftyp":  # MP4 / MOV
        return True
    if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return True
    return False


def probe_video(path: str | Path) -> dict[str, Any]:
    """Return ffprobe metadata, or a structured error when ffprobe is absent."""
    binary = shutil.which("ffprobe")
    if not binary:
        return {"ok": False, "error": "ffprobe not installed"}
    try:
        proc = subprocess.run(
            [
                binary,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": str(error)}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or "ffprobe failed").strip()[:500]}
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        return {"ok": False, "error": "ffprobe returned invalid JSON"}
    video_stream = next(
        (
            stream
            for stream in data.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        None,
    )
    if not video_stream:
        return {"ok": False, "error": "no video stream"}
    duration = data.get("format", {}).get("duration") or video_stream.get("duration")
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_value = None
    return {
        "ok": True,
        "duration_seconds": duration_value,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "codec": video_stream.get("codec_name"),
        "size_bytes": int(data.get("format", {}).get("size") or 0),
    }


def is_vertical(probe: dict[str, Any]) -> bool:
    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    return height > width and height >= 720
