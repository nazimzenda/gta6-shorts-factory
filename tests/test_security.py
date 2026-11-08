from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.storage import store


def test_optional_founder_token_protects_api(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "founder_token", "local-secret")
    unauthorized = client.get("/api/dashboard/summary")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "unauthorized"
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    authorized = client.get(
        "/api/dashboard/summary", headers={"X-Founder-Token": "local-secret"}
    )
    assert authorized.status_code == 200
    bearer = client.get(
        "/api/dashboard/summary", headers={"Authorization": "Bearer local-secret"}
    )
    assert bearer.status_code == 200


def test_expired_rights_block_analysis(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "expired.mp4"
    source.write_bytes(b"fixture")
    asset = client.post("/api/assets/ingest", json={"path": str(source)}).json()
    rights = client.post(
        "/api/rights",
        json={
            "source_asset_id": asset["id"],
            "owner": "Licensor",
            "license_type": "limited",
            "commercial_use": True,
            "expires_at": "2020-01-01T00:00:00Z",
        },
    ).json()
    client.post(
        f"/api/approvals/{rights['approval']['id']}/decision",
        json={"status": "approved"},
    )
    analysis = client.post(f"/api/assets/{asset['id']}/analyze")
    assert analysis.status_code == 403
    assert analysis.json()["code"] == "rights_blocked"


def test_backup_and_report_export_are_created(client: TestClient) -> None:
    backup = client.post("/api/system/backup")
    assert backup.status_code == 201, backup.text
    assert Path(backup.json()["path"]).is_file()
    backups = client.get("/api/system/backups").json()
    assert any(Path(item["path"]).is_file() for item in backups)

    report = client.post("/api/reports/export")
    assert report.status_code == 201, report.text
    path = Path(report.json()["path"])
    assert path.is_file()
    assert "founder-report" in path.name


def test_audit_events_are_append_only_and_queryable(client: TestClient) -> None:
    client.post("/api/tasks", json={"title": "audit task", "department": "operations"})
    events = client.get("/api/system/audit?limit=50").json()
    assert any(event["action"] == "task_created" for event in events)
    ids = [event["id"] for event in events]
    assert ids == sorted(ids, reverse=True)


def test_emergency_stop_stops_cua_sessions(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cua_enabled", True)
    session = client.post(
        "/api/cua/sessions", json={"target": "https://youtube.com", "mode": "observe"}
    ).json()
    client.post(
        f"/api/approvals/{session['approval']['id']}/decision",
        json={"status": "approved"},
    )
    client.post(f"/api/cua/sessions/{session['id']}/activate")
    client.post("/api/system/emergency-stop")
    stored = client.get(f"/api/cua/sessions/{session['id']}").json()
    assert stored["status"] == "stopped"
    client.post("/api/system/resume")


def test_provider_approval_must_match_quote(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "everygen_enabled", True)
    quote = client.post(
        "/api/providers/everygen/quotes",
        json={"request": {"kind": "image", "duration_seconds": 0}},
    ).json()
    client.post(
        f"/api/approvals/{quote['approval']['id']}/decision",
        json={"status": "approved"},
    )
    other = client.post(
        "/api/approvals", json={"type": "mcp_tool", "subject_id": str(uuid.uuid4())}
    ).json()
    client.post(f"/api/approvals/{other['id']}/decision", json={"status": "approved"})
    job = client.post(
        "/api/providers/everygen/jobs",
        json={"quote_id": quote["id"], "approval_id": other["id"]},
    )
    assert job.status_code == 403
    assert job.json()["code"] == "approval_required"


def test_database_integrity_and_schema_version(client: TestClient) -> None:
    detail = client.get("/health/detail").json()
    assert detail["database_integrity"] == "ok"
    version = store.one("SELECT value FROM schema_meta WHERE key = 'version'", (), "")
    assert version["value"] == "2"
