from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load a local .env without adding a runtime dependency."""
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


_load_dotenv()


def flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def number(name: str, default: float, cast: type = float) -> float | int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def listing(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


class Settings:
    """Environment-driven configuration with safe local-first defaults.

    Every external integration is disabled unless its feature flag is set.
    Publishing runs in dry-run mode by default and never contacts a platform.
    """

    def __init__(self) -> None:
        self.company_name = os.getenv("COMPANY_NAME", "GTA 6 Shorts Factory")
        self.app_version = "1.0.0"

        self.data_dir = Path(os.getenv("GTA_DATA_DIR", "data")).expanduser()
        self.database_path = Path(
            os.getenv("GTA_DATABASE_PATH", str(self.data_dir / "factory.db"))
        ).expanduser()
        self.upload_dir = self.data_dir / "uploads"
        self.render_dir = self.data_dir / "renders"
        self.caption_dir = self.data_dir / "captions"
        self.evidence_dir = self.data_dir / "evidence"
        self.provider_dir = self.data_dir / "provider_results"
        self.backup_dir = self.data_dir / "backups"
        self.export_dir = self.data_dir / "exports"

        self.local_processing_enabled = flag("LOCAL_PROCESSING_ENABLED", True)
        self.auto_seed = flag("GTA_AUTO_SEED", True)

        self.everygen_enabled = flag("EVERYGEN_ENABLED", False)
        self.everygen_mock = flag("EVERYGEN_MOCK", True)
        self.everygen_live_url = os.getenv("EVERYGEN_LIVE_URL", "").strip()
        self.everygen_budget_usd = float(number("EVERYGEN_BUDGET_USD", 25.0))
        self.everygen_credit_usd = float(number("EVERYGEN_CREDIT_USD", 0.05))

        self.cua_enabled = flag("CUA_ENABLED", False)
        self.cua_allowed_domains = listing(
            "CUA_ALLOWED_DOMAINS",
            (
                "youtube.com",
                "studio.youtube.com",
                "tiktok.com",
                "www.tiktok.com",
                "localhost",
                "127.0.0.1",
                "example.com",
            ),
        )
        self.cua_session_minutes = int(number("CUA_SESSION_MINUTES", 30, int))
        self.cua_max_actions = int(number("CUA_MAX_ACTIONS", 25, int))

        self.publishing_enabled = flag("PUBLISHING_ENABLED", False)
        self.publishing_dry_run = flag("PUBLISHING_DRY_RUN", True)

        self.mcp_live_enabled = flag("MCP_LIVE_ENABLED", False)

        self.founder_token = os.getenv("FOUNDER_TOKEN", "").strip()
        self.max_upload_mb = int(number("MAX_UPLOAD_MB", 512, int))

        self.min_clip_seconds = float(number("MIN_CLIP_SECONDS", 1.0))
        self.max_clip_seconds = float(number("MAX_CLIP_SECONDS", 90.0))
        self.render_width = int(number("RENDER_WIDTH", 1080, int))
        self.render_height = int(number("RENDER_HEIGHT", 1920, int))
        self.max_render_seconds = int(number("MAX_RENDER_SECONDS", 60, int))
        self.whisper_model = os.getenv("WHISPER_MODEL", "base").strip() or "base"

        self.media_tools = {"ffmpeg": None, "ffprobe": None}

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.database_path.parent,
            self.upload_dir,
            self.render_dir,
            self.caption_dir,
            self.evidence_dir,
            self.provider_dir,
            self.backup_dir,
            self.export_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
