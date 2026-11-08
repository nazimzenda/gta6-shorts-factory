from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline.clipper import (
    ClipWindow,
    ClipperStage,
    Segment,
    apply_caption_fixes,
    parse_vtt,
    render_clip,
    select_windows,
    write_clip_srt,
)
from pipeline.config import PipelineSettings
from pipeline.db import PipelineDB
from pipeline.errors import PipelineError
from pipeline.media import probe_video

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
hello everyone

00:00:02.000 --> 00:00:04.500 align:start position:0%
hello everyone
today we play GTA 6

00:00:04.500 --> 00:00:08.000
no way this police chase is insane
"""


@pytest.fixture
def settings(tmp_path: Path) -> PipelineSettings:
    value = PipelineSettings()
    value.mode = "clip"
    value.data_dir = tmp_path / "pipeline"
    value.db_path = value.data_dir / "pipeline.db"
    value.videos_dir.mkdir(parents=True, exist_ok=True)
    value.sources_dir.mkdir(parents=True, exist_ok=True)
    value.rights_ack = False
    return value


def test_parse_vtt_dedupes_rolling_captions(tmp_path: Path) -> None:
    path = tmp_path / "captions.vtt"
    path.write_text(VTT, encoding="utf-8")
    segments = parse_vtt(path)
    assert len(segments) == 3
    assert "hello everyone" in segments[0].text
    assert segments[1].text == "today we play GTA 6"
    assert "GTA 6" in segments[1].text
    assert segments[1].start == 2.0
    assert segments[1].end == 4.5


def test_select_windows_from_captions() -> None:
    segments = [
        Segment(0, 5, "hello everyone welcome back"),
        Segment(5, 12, "today we play GTA 6 and the police chase is insane"),
        Segment(12, 18, "no way that explosion was crazy"),
        Segment(30, 40, "another mission and a funny fail"),
        Segment(60, 70, "secret found in the new gameplay"),
    ]
    windows = select_windows(
        segments,
        90,
        count=2,
        min_seconds=10,
        max_seconds=30,
        target_seconds=20,
        fallback_title="GTA 6 stream",
    )
    assert 1 <= len(windows) <= 2
    assert all(10 <= window.duration <= 30 for window in windows)
    # non-overlapping
    ordered = sorted(windows, key=lambda window: window.start)
    for first, second in zip(ordered, ordered[1:]):
        assert first.end <= second.start


def test_select_windows_without_captions() -> None:
    windows = select_windows(
        [],
        300,
        count=3,
        min_seconds=15,
        max_seconds=60,
        target_seconds=35,
        fallback_title="GTA 6 stream",
    )
    assert len(windows) == 3
    assert all(window.end > window.start for window in windows)
    assert "no captions" in windows[0].reason


def test_short_source_becomes_one_clip() -> None:
    windows = select_windows(
        [],
        20,
        count=3,
        min_seconds=15,
        max_seconds=60,
        target_seconds=35,
    )
    assert len(windows) == 1
    assert windows[0].start == 0
    assert windows[0].end == 20


def test_write_srt_is_relative_to_window(tmp_path: Path) -> None:
    segments = [Segment(12, 15, "hello"), Segment(20, 24, "world")]
    path = write_clip_srt(segments, 10, 25, tmp_path / "clip.srt")
    assert path is not None
    text = path.read_text()
    assert "00:00:02,000 --> 00:00:05,000" in text
    assert "00:00:10,000 --> 00:00:14,000" in text


def test_caption_typo_fix(settings: PipelineSettings) -> None:
    assert (
        apply_caption_fixes("downtown Viciti looks amazing", settings)
        == "downtown Vice City looks amazing"
    )
    assert (
        apply_caption_fixes("VICITI at night", settings) == "Vice City at night"
    )
    assert apply_caption_fixes("nothing to change", settings) == "nothing to change"


def test_rights_gate(settings: PipelineSettings) -> None:
    db = PipelineDB(settings.db_path)
    stage = ClipperStage(settings, db)
    with pytest.raises(PipelineError, match="rights"):
        stage.require_rights()
    settings.rights_ack = True
    stage.require_rights()
    db.close()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_render_clip_outputs_vertical_video(
    settings: PipelineSettings, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "4",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    output = settings.videos_dir / "clip.mp4"
    rendered = render_clip(
        source,
        0,
        3,
        output,
        title="Test GTA 6 clip",
        segments=[Segment(0, 2, "hello world")],
        window_start=0,
        window_end=3,
        settings=settings,
    )
    assert Path(rendered["path"]).is_file()
    probe = probe_video(output)
    assert probe["ok"] is True
    assert probe["width"] == 1080
    assert probe["height"] == 1920
    assert 2.5 <= float(probe["duration_seconds"]) <= 3.5
    assert output.with_suffix(".srt").is_file()
