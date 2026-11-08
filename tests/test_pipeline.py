from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.config import PipelineSettings
from pipeline.db import PipelineDB
from pipeline.errors import PlanRequired
from pipeline.everygen import EverygenStage
from pipeline.guest_runner import JobResult
from pipeline.media import looks_like_video
from pipeline.orchestrator import Pipeline
from pipeline.yt_search import (
    VideoLink,
    age_hours,
    discover,
    parse_search_html,
    views_to_int,
)


@pytest.fixture
def settings(tmp_path: Path) -> PipelineSettings:
    value = PipelineSettings()
    value.mode = "generate"
    value.data_dir = tmp_path / "pipeline"
    value.db_path = value.data_dir / "pipeline.db"
    value.cua_enabled = True
    value.require_auth_check = False
    value.platforms = ["youtube"]
    value.variants_per_link = 1
    value.max_shorts_per_cycle = 1
    value.links_per_cycle = 1
    value.video_min_bytes = 100
    value.everygen_budget_credits = 0
    value.retry_limit = 2
    value.ensure_dirs()
    return value


@pytest.fixture
def db(settings: PipelineSettings) -> PipelineDB:
    database = PipelineDB(settings.db_path)
    yield database
    database.close()


# --------------------------------------------------------------------- database
def test_link_generation_and_post_idempotency(db: PipelineDB) -> None:
    link_id, created = db.add_link(
        {
            "url": "https://www.youtube.com/watch?v=abc123",
            "video_id": "abc123",
            "title": "GTA 6 test",
            "query": "gta 6",
        }
    )
    assert created is True
    duplicate_id, created_again = db.add_link(
        {"url": "https://www.youtube.com/watch?v=abc123", "video_id": "abc123"}
    )
    assert created_again is False
    assert duplicate_id == link_id

    claimed = db.claim_links(1)
    assert len(claimed) == 1
    assert claimed[0]["status"] == "generating"
    assert db.get_link(link_id)["attempts"] == 1

    generation_id = db.create_generation(link_id, 0, direction="make a short")
    assert generation_id > 0
    same_id = db.create_generation(link_id, 0, direction="duplicate")
    assert same_id == generation_id

    db.enqueue_posts(generation_id, ["youtube", "tiktok"])
    posts = db.posts_for_generation(generation_id)
    assert {post["platform"] for post in posts} == {"youtube", "tiktok"}
    db.enqueue_posts(generation_id, ["youtube"])
    assert len(db.posts_for_generation(generation_id)) == 2

    db.update_generation(generation_id, status="ready", host_path="/tmp/video.mp4")
    publishable = db.publishable_generations(["youtube"], limit=10)
    assert [row["id"] for row in publishable] == [generation_id]


def test_pending_variants_retries_failures_with_a_cap(db: PipelineDB) -> None:
    link_id, _ = db.add_link({"url": "https://youtu.be/abc"})
    generation_id = db.create_generation(link_id, 0)
    db.update_generation(generation_id, status="failed", attempts=0)
    assert db.pending_variants(link_id, 3, retry_limit=2) == [0, 1, 2]
    db.update_generation(generation_id, status="failed", attempts=2)
    assert db.pending_variants(link_id, 3, retry_limit=2) == [1, 2]
    db.update_generation(generation_id, status="skipped", attempts=0)
    assert db.pending_variants(link_id, 3, retry_limit=2) == [1, 2]
    db.update_generation(generation_id, status="deferred", attempts=99)
    assert db.pending_variants(link_id, 3, retry_limit=2) == [0, 1, 2]


def test_credit_and_daily_post_counters(db: PipelineDB) -> None:
    link_id, _ = db.add_link({"url": "https://youtu.be/abc"})
    generation_id = db.create_generation(link_id, 0)
    db.update_generation(generation_id, credits=39)
    assert db.credits_spent() == 39.0

    db.enqueue_posts(generation_id, ["youtube"])
    post = db.posts_for_generation(generation_id)[0]
    db.update_post(post["id"], status="published", live=1)
    assert db.daily_published_count("youtube") == 1
    assert db.daily_published_count("tiktok") == 0


def test_stats_shape(db: PipelineDB) -> None:
    stats = db.stats()
    assert stats["links"]["new"] == 0
    assert stats["generations"]["pending"] == 0
    assert stats["posts"]["pending"] == 0
    assert stats["db_path"].endswith("pipeline.db")


# ------------------------------------------------------------------- discovery
def test_parse_youtube_search_payload() -> None:
    payload = {
        "contents": {
            "videoRenderer": {
                "videoId": "abc123",
                "title": {"runs": [{"text": "GTA 6 Launch Trailer"}]},
                "ownerText": {"runs": [{"text": "Rockstar Games"}]},
                "lengthText": {"simpleText": "1:31"},
                "viewCountText": {"simpleText": "74,897,829 views"},
                "publishedTimeText": {"simpleText": "3w ago"},
                "thumbnailOverlays": [
                    {"thumbnailOverlayTimeStatusRenderer": {"style": "DEFAULT"}}
                ],
            }
        }
    }
    html = f"<script>var ytInitialData = {json.dumps(payload)};</script>"
    links = parse_search_html(html, "gta 6")
    assert len(links) == 1
    link = links[0]
    assert link.url == "https://www.youtube.com/watch?v=abc123"
    assert link.title == "GTA 6 Launch Trailer"
    assert link.channel == "Rockstar Games"
    assert link.query == "gta 6"
    assert link.is_short is False


def test_parse_short_renderer_marks_short_url() -> None:
    payload = {
        "videoRenderer": {
            "videoId": "short1",
            "title": {"simpleText": "GTA 6 Short"},
            "viewCountText": {"simpleText": "1.2M views"},
            "publishedTimeText": {"simpleText": "2h ago"},
            "navigationEndpoint": {
                "commandMetadata": {"webCommandMetadata": {"url": "/shorts/short1"}}
            },
        }
    }
    html = f"<script>var ytInitialData = {json.dumps(payload)};</script>"
    links = parse_search_html(html)
    assert links[0].url == "https://www.youtube.com/shorts/short1"
    assert links[0].is_short is True


def test_view_count_and_age_parsing() -> None:
    assert views_to_int("74,897,829 views") == 74_897_829
    assert views_to_int("1.2M views") == 1_200_000
    assert views_to_int("12K views") == 12_000
    assert views_to_int("No views") == 0
    assert age_hours("3h ago") == 3
    assert age_hours("2d ago") == 48
    assert age_hours("2w ago") == 336
    assert age_hours("2mo ago") == 1440
    assert age_hours("1y ago") == 8760


def test_discover_dedupes_and_ranks(monkeypatch: pytest.MonkeyPatch) -> None:
    older = VideoLink(
        url="https://youtu.be/old",
        video_id="old",
        title="old",
        view_count="1,000 views",
        published="1y ago",
    )
    newer = VideoLink(
        url="https://youtu.be/new",
        video_id="new",
        title="new",
        view_count="10,000 views",
        published="1d ago",
    )
    duplicate = VideoLink(
        url="https://youtu.be/new",
        video_id="new",
        title="new duplicate",
        view_count="10,000 views",
        published="1d ago",
    )
    monkeypatch.setattr(
        "pipeline.yt_search.search",
        lambda *args, **kwargs: [older, newer, duplicate],
    )
    result = discover(["gta 6"], per_query=10, sleep_range=(0, 0))
    assert [link.video_id for link in result] == ["new", "old"]


# -------------------------------------------------------------------- everygen
def test_everygen_prompt_contains_source_and_direction(
    settings: PipelineSettings, db: PipelineDB
) -> None:
    stage = EverygenStage(settings, db, guest=None)  # type: ignore[arg-type]
    prompt = stage.build_direction(
        {
            "url": "https://www.youtube.com/watch?v=abc123",
            "title": "GTA 6 Extended Look",
        },
        0,
    )
    assert "https://www.youtube.com/watch?v=abc123" in prompt
    assert "GTA 6 Extended Look" in prompt
    assert "9:16" in prompt
    assert len(prompt) <= 2000


# ----------------------------------------------------------------------- cycle
class FakeSandbox:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def ensure_running(self, timeout: int = 300):
        return {"ok": True, "state": "running", "name": "fake"}

    def status(self):
        return {"ok": True, "enabled": True, "state": "running", "name": "fake"}

    def view_url(self):
        return "http://fake-viewer"

    def copy_from_guest(self, remote_path: str, local_path: Path):
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(b"fake-video" * 200)

    def copy_to_guest(self, local_path: Path, remote_path: str):
        return None


class FakeGuest:
    def __init__(
        self,
        tmp_path: Path,
        auth_failure: bool = False,
        plan_failure: bool = False,
    ) -> None:
        self.sandbox = FakeSandbox(tmp_path)
        self.auth_failure = auth_failure
        self.plan_failure = plan_failure
        self.local_guest_dir = Path(__file__).resolve().parents[1] / "pipeline" / "guest"
        self.generated = 0
        self.published = 0

    def ensure(self):
        return {"ok": True}

    def deploy(self):
        return {"ok": True}

    def generate_video(self, **kwargs):
        if self.auth_failure:
            return JobResult(
                ok=False,
                label="everygen",
                exit_code=2,
                payload={"ok": False, "error": "NOT_LOGGED_IN"},
                error="NOT_LOGGED_IN",
            )
        if self.plan_failure:
            return JobResult(
                ok=False,
                label="everygen",
                exit_code=1,
                payload={"ok": False, "error": "PLAN_REQUIRED"},
                error="PLAN_REQUIRED",
            )
        self.generated += 1
        return JobResult(
            ok=True,
            label="everygen",
            exit_code=0,
            payload={
                "ok": True,
                "videos": [
                    {
                        "path": "/home/cua/Downloads/everygen/fake.mp4",
                        "title": "Fake GTA Short",
                        "credits": 39,
                    }
                ],
            },
        )

    def publish_youtube(self, **kwargs):
        self.published += 1
        return JobResult(
            ok=True,
            label="youtube-upload",
            exit_code=0,
            payload={"ok": True, "note": "dry-run stopped before Publish"},
        )

    def publish_tiktok(self, **kwargs):  # pragma: no cover - not used in test
        return JobResult(ok=True, label="tiktok-upload", payload={"ok": True})


def _link(video_id: str = "abc123") -> VideoLink:
    return VideoLink(
        url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
        title="GTA 6 test source",
        channel="Test",
        view_count="1,000 views",
        published="1d ago",
        query="gta 6 test",
    )


def test_full_cycle_with_fake_cua_guest(
    settings: PipelineSettings, db: PipelineDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pipeline.orchestrator.discover", lambda *args, **kwargs: [_link()]
    )
    monkeypatch.setattr("pipeline.everygen.looks_like_video", lambda path: True)
    monkeypatch.setattr(
        "pipeline.everygen.probe_video",
        lambda path: {
            "ok": True,
            "width": 1080,
            "height": 1920,
            "duration_seconds": 10.0,
        },
    )
    guest = FakeGuest(settings.data_dir)
    pipeline = Pipeline(
        settings, db=db, sandbox=guest.sandbox, guest=guest  # type: ignore[arg-type]
    )
    result = pipeline.cycle(live=False, max_shorts=1)
    assert result.status == "completed"
    assert guest.generated == 1
    assert guest.published == 1
    assert db.links(status="generated")[0]["url"].endswith("abc123")
    assert db.generations(status="ready")
    posts = db.posts()
    assert len(posts) == 1
    assert posts[0]["status"] == "dry_run"


def test_cycle_stops_cleanly_when_everygen_is_logged_out(
    settings: PipelineSettings, db: PipelineDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pipeline.orchestrator.discover", lambda *args, **kwargs: [_link("logout")]
    )
    guest = FakeGuest(settings.data_dir, auth_failure=True)
    pipeline = Pipeline(
        settings, db=db, sandbox=guest.sandbox, guest=guest  # type: ignore[arg-type]
    )
    result = pipeline.cycle(live=False, max_shorts=1)
    assert result.status == "auth_required"
    assert result.auth_required is True
    assert db.links(status="new")[0]["error"] == "NOT_LOGGED_IN"
    generation = db.generations()[0]
    assert generation["status"] == "pending"


# ---------------------------------------------------------- guard rails
def test_plan_required_is_deferred_and_link_requeued(
    settings: PipelineSettings, db: PipelineDB
) -> None:
    link_id, _ = db.add_link(
        {"url": "https://www.youtube.com/watch?v=plan", "title": "GTA 6 plan test"}
    )
    guest = FakeGuest(settings.data_dir, plan_failure=True)
    stage = EverygenStage(settings, db, guest)  # type: ignore[arg-type]
    with pytest.raises(PlanRequired):
        stage.generate_link(db.get_link(link_id), variants=1)
    link = db.get_link(link_id)
    assert link["status"] == "new"
    assert "PLAN" in (link["error"] or "").upper() or "plan" in (
        link["error"] or ""
    ).lower()
    generation = db.generations()[0]
    assert generation["status"] == "deferred"
    assert "plan" in (generation["error"] or "").lower()


def test_emergency_stop_blocks_cycle(
    settings: PipelineSettings, db: PipelineDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.respect_factory_emergency_stop = False
    assert Pipeline(settings, db=db).emergency_stopped() is False
    settings.respect_factory_emergency_stop = True
    settings.factory_db = settings.data_dir / "factory.db"
    import sqlite3

    connection = sqlite3.connect(settings.factory_db)
    connection.execute(
        "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO system_state (key, value) VALUES ('emergency_stop', 'true')"
    )
    connection.commit()
    connection.close()
    pipeline = Pipeline(settings, db=db)
    assert pipeline.emergency_stopped() is True
    result = pipeline.cycle(live=False)
    assert result.status == "failed"
    assert "emergency stop" in (result.error or "").lower()


def test_cua_specific_emergency_stop_is_honored(
    settings: PipelineSettings, db: PipelineDB
) -> None:
    import sqlite3

    settings.factory_db = settings.data_dir / "factory.db"
    connection = sqlite3.connect(settings.factory_db)
    connection.execute(
        "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO system_state (key, value) VALUES ('emergency_stop', 'false')"
    )
    connection.execute(
        "INSERT INTO system_state (key, value) VALUES ('cua_emergency_stop', 'true')"
    )
    connection.commit()
    connection.close()
    assert Pipeline(settings, db=db).emergency_stopped() is True


# --------------------------------------------------------- guest script helpers
def _load_guest_module(name: str):
    path = Path(__file__).resolve().parents[1] / "pipeline" / "guest" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_video_container_sniffing(tmp_path: Path) -> None:
    html = tmp_path / "error.mp4"
    html.write_bytes(b"<html><body>rate limited</body></html>")
    assert looks_like_video(html) is False
    mp4 = tmp_path / "real.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    assert looks_like_video(mp4) is True
    webm = tmp_path / "real.webm"
    webm.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 64)
    assert looks_like_video(webm) is True


def test_guest_everygen_pure_helpers(tmp_path: Path) -> None:
    module = _load_guest_module("guest_everygen.py")
    assert module._parse_title("Open video: GTA 6 drift", "fallback") == "GTA 6 drift"
    assert module._parse_title("", "fallback") == "fallback"
    module.DOWNLOAD_DIR = str(tmp_path)
    module.MIN_VIDEO_BYTES = 10
    (tmp_path / "old.mp4").write_bytes(b"x" * 100)
    before = module._snapshot_download_dir(str(tmp_path))
    (tmp_path / "new.mp4").write_bytes(b"x" * 100)
    found = module._new_download(str(tmp_path), before, timeout=1)
    assert found and found.endswith("new.mp4")


def test_everygen_session_probe() -> None:
    class FakeDriver:
        def __init__(self, response):
            self.response = response

        def execute_async_script(self, script, *args):
            return self.response

    everygen = _load_guest_module("guest_everygen.py")
    accounts = _load_guest_module("guest_accounts.py")
    for module in (everygen, accounts):
        assert module._everygen_session_state(
            FakeDriver({"status": 200, "body": "null"})
        ) is False
        assert module._everygen_session_state(
            FakeDriver({"status": 200, "body": '{"session": {"id": "s"}}'})
        ) is True
        assert module._everygen_session_state(
            FakeDriver({"status": 200, "body": '{"user": {"id": "u"}}'})
        ) is True
        assert module._everygen_session_state(
            FakeDriver({"status": 401, "body": ""})
        ) is None


def test_guest_accounts_imports_cleanly() -> None:
    module = _load_guest_module("guest_accounts.py")
    assert hasattr(module, "main")
    assert hasattr(module, "_everygen_logged_in")


def test_guest_upload_scripts_import_cleanly() -> None:
    for name in ("upload_yt.py", "upload_tiktok.py"):
        module = _load_guest_module(name)
        assert hasattr(module, "is_logged_in_url")


def test_pipeline_dashboard_api_is_read_only(client) -> None:
    status = client.get("/api/pipeline/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["ok"] is True
    assert "db" in body and "settings" in body
    assert client.get("/api/pipeline/links").status_code == 200
    assert client.get("/api/pipeline/generations").status_code == 200
    assert client.get("/api/pipeline/posts").status_code == 200
    assert client.get("/api/pipeline/runs").status_code == 200
    assert client.get("/api/pipeline/events").status_code == 200
    assert client.get("/api/pipeline/showcase").status_code == 200


def test_pipeline_live_publish_requires_confirmations(client) -> None:
    response = client.post(
        "/api/pipeline/publish",
        json={"live": True, "confirm": False, "rights_ack": False},
    )
    assert response.status_code == 400
    assert "confirm" in response.text.lower()


def test_pipeline_clip_requires_rights_ack(client) -> None:
    response = client.post(
        "/api/pipeline/clip",
        json={
            "urls": ["https://www.youtube.com/watch?v=example"],
            "count": 1,
            "rights_ack": False,
        },
    )
    assert response.status_code == 400
    assert "rights" in response.text.lower()
