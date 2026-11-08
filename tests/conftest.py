from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="gta6-shorts-tests-"))
os.environ["GTA_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["GTA_DATABASE_PATH"] = str(TEST_DATA_DIR / "factory.db")
os.environ["GTA_AUTO_SEED"] = "true"
os.environ["EVERYGEN_ENABLED"] = "false"
os.environ["CUA_ENABLED"] = "false"
os.environ["PUBLISHING_ENABLED"] = "false"
os.environ["PUBLISHING_DRY_RUN"] = "true"
os.environ["MCP_LIVE_ENABLED"] = "false"
os.environ["FOUNDER_TOKEN"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_defaults  # noqa: E402
from app.storage import store  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    store.reset_domain_data()
    seed_defaults(store)
    settings.everygen_enabled = False
    settings.everygen_mock = True
    settings.cua_enabled = False
    settings.publishing_enabled = False
    settings.publishing_dry_run = True
    settings.mcp_live_enabled = False
    settings.local_processing_enabled = True
    settings.founder_token = ""
    settings.cua_allowed_domains = (
        "youtube.com",
        "studio.youtube.com",
        "tiktok.com",
        "www.tiktok.com",
        "localhost",
        "127.0.0.1",
        "example.com",
    )
    settings.cua_max_actions = 25
    settings.cua_session_minutes = 30
    settings.everygen_budget_usd = 25.0
    yield
    settings.everygen_enabled = False
    settings.cua_enabled = False
    settings.founder_token = ""


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def sample_video() -> Path:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for media pipeline tests")
    path = TEST_DATA_DIR / "fixtures" / "sample.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=30",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440",
                "-t",
                "2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    return path


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
