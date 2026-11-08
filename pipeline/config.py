"""Environment-driven configuration for the CUA pipeline.

Everything external is off by default.  Live publishing is opt-in through
``PIPELINE_LIVE=true`` or ``--live``; a normal run stops on the platform's
review screen and records a dry-run result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


ROOT = Path(__file__).resolve().parents[1]
_load_dotenv(ROOT / ".env")


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _list(name: str, default: tuple[str, ...]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _pairs(name: str, default: dict[str, str]) -> dict[str, str]:
    raw = os.getenv(name)
    if raw is None:
        return dict(default)
    pairs: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            pairs[key] = value.strip()
    return pairs or dict(default)


def _default_pipeline_data_dir() -> Path:
    """Pipeline data lives under GTA_DATA_DIR unless explicitly overridden.

    Keeping the base aligned with the control tower means tests that point
    GTA_DATA_DIR at a temp directory never touch the owner's real pipeline.db.
    """
    explicit = os.getenv("GTA_PIPELINE_DATA_DIR")
    if explicit:
        return Path(explicit).expanduser()
    base = os.getenv("GTA_DATA_DIR", str(ROOT / "data"))
    return Path(base).expanduser() / "pipeline"


@dataclass
class PipelineSettings:
    """All knobs for one pipeline process.  Never import credentials here."""

    root: Path = field(default_factory=lambda: ROOT)

    # ---------------------------------------------------------- CUA sandbox
    cua_enabled: bool = field(default_factory=lambda: _flag("CUA_ENABLED", False))
    cua_cli: str = field(default_factory=lambda: os.getenv("CUA_CLI", "").strip())
    cua_name: str = field(
        default_factory=lambda: os.getenv("CUA_SANDBOX_NAME", "dev").strip() or "dev"
    )
    cua_kind: str = field(
        default_factory=lambda: os.getenv("CUA_KIND", "vm").strip() or "vm"
    )
    cua_image: str = field(default_factory=lambda: os.getenv("CUA_IMAGE", "").strip())
    cua_home: str = field(
        default_factory=lambda: os.getenv("CUA_HOME", "").strip()
        or str(Path.home() / ".cua")
    )

    # Guest paths (the VM is the owner's signed-in browser machine)
    guest_profile: str = field(
        default_factory=lambda: os.getenv(
            "CUA_GUEST_PROFILE",
            "/home/cua/.config/mozilla/firefox/5s77mr7y.default-release",
        )
    )
    guest_venv: str = field(
        default_factory=lambda: os.getenv(
            "CUA_GUEST_VENV", "/home/cua/venv/bin/python3"
        )
    )
    guest_media_dir: str = field(
        default_factory=lambda: os.getenv("CUA_GUEST_MEDIA_DIR", "/home/cua/media")
    )
    guest_run_dir: str = field(
        default_factory=lambda: os.getenv(
            "CUA_GUEST_RUN_DIR", "/home/cua/gta_pipeline"
        )
    )
    guest_download_dir: str = field(
        default_factory=lambda: os.getenv(
            "CUA_GUEST_DOWNLOAD_DIR", "/home/cua/Downloads/everygen"
        )
    )
    guest_display: str = field(
        default_factory=lambda: os.getenv("CUA_GUEST_DISPLAY", ":1")
    )

    # ------------------------------------------------------------- local data
    data_dir: Path = field(default_factory=_default_pipeline_data_dir)
    db_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "GTA_PIPELINE_DB",
                str(_default_pipeline_data_dir() / "pipeline.db"),
            )
        ).expanduser()
    )

    # --------------------------------------------------------------- mode
    # generate = Everygen AI clips (paid); clip = cut highlights from a
    # YouTube source (free, local ffmpeg, rights acknowledgement required).
    mode: str = field(
        default_factory=lambda: os.getenv("PIPELINE_MODE", "generate").strip().lower()
    )
    rights_ack: bool = field(
        default_factory=lambda: _flag("PIPELINE_RIGHTS_ACK", False)
    )

    # ------------------------------------------------------------- discovery
    queries: list[str] = field(
        default_factory=lambda: _list(
            "PIPELINE_QUERIES",
            (
                "gta 6 trailer",
                "gta 6 gameplay",
                "gta 6 news",
                "gta 6 secrets",
                "gta 6 shorts",
            ),
        )
    )
    links_per_cycle: int = field(
        default_factory=lambda: _int("PIPELINE_LINKS_PER_CYCLE", 3)
    )
    results_per_query: int = field(
        default_factory=lambda: _int("PIPELINE_RESULTS_PER_QUERY", 20)
    )
    min_views: int = field(default_factory=lambda: _int("PIPELINE_MIN_VIEWS", 0))
    search_timeout: int = field(
        default_factory=lambda: _int("PIPELINE_SEARCH_TIMEOUT", 25)
    )

    # ------------------------------------------------------------- Everygen
    everygen_url: str = field(
        default_factory=lambda: os.getenv(
            "EVERYGEN_URL", "https://everygen.ai/tools/shorts-studio"
        )
    )
    everygen_format: str = field(
        default_factory=lambda: os.getenv("EVERYGEN_FORMAT", "GTA 6")
    )
    everygen_model: str = field(
        default_factory=lambda: os.getenv("EVERYGEN_MODEL", "Seedance 2.5")
    )
    everygen_quality: str = field(
        default_factory=lambda: os.getenv("EVERYGEN_QUALITY", "720p")
    )
    everygen_duration: str = field(
        default_factory=lambda: os.getenv("EVERYGEN_DURATION", "10s")
    )
    variants_per_link: int = field(
        default_factory=lambda: _int("PIPELINE_VARIANTS_PER_LINK", 2)
    )
    max_shorts_per_cycle: int = field(
        default_factory=lambda: _int("PIPELINE_MAX_SHORTS_PER_CYCLE", 4)
    )
    everygen_budget_credits: float = field(
        default_factory=lambda: _float("EVERYGEN_CREDIT_BUDGET", 0.0)
    )
    everygen_estimated_credits: float = field(
        default_factory=lambda: _float("EVERYGEN_ESTIMATED_CREDITS", 39.0)
    )
    everygen_timeout: int = field(
        default_factory=lambda: _int("EVERYGEN_TIMEOUT", 1800)
    )
    everygen_auto_approve: bool = field(
        default_factory=lambda: _flag("EVERYGEN_AUTO_APPROVE", True)
    )
    everygen_prompt_prefix: str = field(
        default_factory=lambda: os.getenv(
            "EVERYGEN_PROMPT_PREFIX",
            (
                "Make an original photoreal GTA 6 style vertical short with "
                "sound. Use the reference only for the topic, hook and energy; "
                "do not recreate its footage, logo, characters or music. "
            ),
        ).strip()
    )

    # ---------------------------------------------------------------- clipping
    clip_count: int = field(default_factory=lambda: _int("PIPELINE_CLIPS_PER_VIDEO", 2))
    clip_min_seconds: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_MIN_SECONDS", 15)
    )
    clip_max_seconds: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_MAX_SECONDS", 60)
    )
    clip_target_seconds: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_TARGET_SECONDS", 35)
    )
    clip_quality: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_QUALITY", 1080)
    )
    clip_layout: str = field(
        default_factory=lambda: os.getenv("PIPELINE_CLIP_LAYOUT", "streamer").strip().lower()
    )
    clip_facecam_crop: str = field(
        default_factory=lambda: os.getenv(
            "PIPELINE_CLIP_FACECAM_CROP", "0.80,0.00,1.00,0.30"
        ).strip()
    )
    clip_facecam_width: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_FACECAM_WIDTH", 280)
    )
    clip_facecam_margin: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_FACECAM_MARGIN", 36)
    )
    clip_caption_size: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_CAPTION_SIZE", 12)
    )
    clip_caption_margin: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_CAPTION_MARGIN", 24)
    )
    caption_fixes: dict[str, str] = field(
        default_factory=lambda: _pairs(
            "PIPELINE_CLIP_CAPTION_FIXES", {"Viciti": "Vice City"}
        )
    )
    clip_show_title: bool = field(
        default_factory=lambda: _flag("PIPELINE_CLIP_SHOW_TITLE", True)
    )
    clip_show_captions: bool = field(
        default_factory=lambda: _flag("PIPELINE_CLIP_SHOW_CAPTIONS", True)
    )
    clip_transcribe_fallback: bool = field(
        default_factory=lambda: _flag("PIPELINE_CLIP_TRANSCRIBE_FALLBACK", True)
    )
    whisper_python: str = field(
        default_factory=lambda: os.getenv("PIPELINE_WHISPER_PYTHON", "").strip()
    )
    whisper_model: str = field(
        default_factory=lambda: os.getenv("PIPELINE_WHISPER_MODEL", "base").strip()
        or "base"
    )
    whisper_timeout: int = field(
        default_factory=lambda: _int("PIPELINE_WHISPER_TIMEOUT", 900)
    )
    clip_max_source_seconds: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_MAX_SOURCE_SECONDS", 7200)
    )
    clip_max_full_download_seconds: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_MAX_FULL_DOWNLOAD_SECONDS", 900)
    )
    clip_download_timeout: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_DOWNLOAD_TIMEOUT", 1200)
    )
    clip_render_timeout: int = field(
        default_factory=lambda: _int("PIPELINE_CLIP_RENDER_TIMEOUT", 600)
    )
    clip_subtitle_langs: str = field(
        default_factory=lambda: os.getenv(
            "PIPELINE_CLIP_SUBTITLE_LANGS", "en.*,en"
        ).strip()
    )
    clip_title_prefix: str = field(
        default_factory=lambda: os.getenv(
            "PIPELINE_CLIP_TITLE_PREFIX", "Streamer Moment | GTA 6"
        ).strip()
    )
    yt_dlp_bin: str = field(
        default_factory=lambda: os.getenv("PIPELINE_YTDLP_BIN", "").strip()
    )

    # -------------------------------------------------------------- publishing
    platforms: list[str] = field(
        default_factory=lambda: _list(
            "PIPELINE_PLATFORMS", ("youtube", "tiktok")
        )
    )
    live: bool = field(default_factory=lambda: _flag("PIPELINE_LIVE", False))
    dry_run: bool = field(default_factory=lambda: _flag("PIPELINE_DRY_RUN", True))
    publish_timeout: int = field(
        default_factory=lambda: _int("PIPELINE_PUBLISH_TIMEOUT", 1500)
    )
    daily_limit_youtube: int = field(
        default_factory=lambda: _int("PIPELINE_DAILY_LIMIT_YOUTUBE", 3)
    )
    daily_limit_tiktok: int = field(
        default_factory=lambda: _int("PIPELINE_DAILY_LIMIT_TIKTOK", 3)
    )
    youtube_hashtags: str = field(
        default_factory=lambda: os.getenv(
            "PIPELINE_YOUTUBE_HASHTAGS", "#GTA6 #GTA #Shorts #Gaming"
        ).strip()
    )
    tiktok_hashtags: str = field(
        default_factory=lambda: os.getenv(
            "PIPELINE_TIKTOK_HASHTAGS", "#gta6 #gta #shorts #gaming #fyp"
        ).strip()
    )
    video_min_bytes: int = field(
        default_factory=lambda: _int("PIPELINE_VIDEO_MIN_BYTES", 50_000)
    )

    # ------------------------------------------------------------- guard rails
    require_auth_check: bool = field(
        default_factory=lambda: _flag("PIPELINE_REQUIRE_AUTH_CHECK", True)
    )
    respect_factory_emergency_stop: bool = field(
        default_factory=lambda: _flag("PIPELINE_RESPECT_EMERGENCY_STOP", True)
    )
    factory_db: Path = field(
        default_factory=lambda: Path(
            os.getenv("GTA_DATABASE_PATH", str(ROOT / "data" / "factory.db"))
        ).expanduser()
    )
    retry_limit: int = field(default_factory=lambda: _int("PIPELINE_RETRY_LIMIT", 2))
    log_level: str = field(
        default_factory=lambda: os.getenv("PIPELINE_LOG_LEVEL", "INFO").upper()
    )

    # ------------------------------------------------------------- derived
    def __post_init__(self) -> None:
        self.platforms = [platform.lower() for platform in self.platforms]

    @property
    def videos_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def guest_script_dir(self) -> str:
        return f"{self.guest_run_dir}/scripts"

    @property
    def guest_runs_dir(self) -> str:
        return f"{self.guest_run_dir}/runs"

    def ensure_dirs(self) -> None:
        for directory in (
            self.data_dir,
            self.db_path.parent,
            self.videos_dir,
            self.sources_dir,
            self.evidence_dir,
            self.logs_dir,
            self.screenshots_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def platform_enabled(self, platform: str) -> bool:
        return platform in {p.lower() for p in self.platforms}


def load_settings() -> PipelineSettings:
    """Build a fresh settings object (tests can call this after monkeypatching)."""
    return PipelineSettings()


settings = load_settings()
