from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.services import FactoryService
from app.storage import Store


def test_approval_workflow_and_task_execution(client: TestClient) -> None:
    approval = client.post(
        "/api/approvals",
        json={"type": "rights", "subject_id": "source-demo", "reason": "fixture review"},
    )
    assert approval.status_code == 201
    approval_id = approval.json()["id"]

    decision = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"status": "approved", "note": "evidence checked"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert decision.json()["decided_by"] == "founder"

    second = client.post(
        f"/api/approvals/{approval_id}/decision", json={"status": "rejected"}
    )
    assert second.status_code == 409

    task = client.post(
        "/api/tasks",
        json={"title": "Review source rights", "department": "research"},
    )
    assert task.status_code == 201
    task_id = task.json()["id"]

    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["evidence"]["kind"] == "department_evidence"

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert [event["event_type"] for event in detail["events"]] == ["created", "started", "completed"]


def test_provider_and_cua_are_blocked_by_default(client: TestClient) -> None:
    provider = client.post(
        "/api/providers/everygen/jobs", json={"quote_id": "missing-quote"}
    )
    cua = client.post(
        "/api/cua/sessions", json={"target": "example.com", "mode": "observe"}
    )
    quote = client.post(
        "/api/providers/everygen/quotes", json={"request": {"kind": "video"}}
    )
    assert provider.status_code == 403
    assert cua.status_code == 403
    assert quote.status_code == 403
    assert provider.json()["code"] == "policy_blocked"


def test_ingest_requires_approved_commercial_rights(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("fixture", encoding="utf-8")
    service = FactoryService(Store(tmp_path / "test.db"))
    try:
        service.ingest_asset(str(source), "missing-rights")
    except PermissionError as error:
        assert "approved commercial rights" in str(error)
    else:
        raise AssertionError("ingest unexpectedly bypassed rights gate")


def test_rights_record_creation_creates_approval_and_updates_asset(
    client: TestClient, tmp_path: Path
) -> None:
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"not a real video")
    ingest = client.post(
        "/api/assets/ingest",
        json={"path": str(source), "owner": "Founder"},
    )
    assert ingest.status_code == 201
    asset_id = ingest.json()["id"]
    assert ingest.json()["status"] == "pending_rights"

    rights = client.post(
        "/api/rights",
        json={
            "source_asset_id": asset_id,
            "owner": "Founder",
            "license_type": "owned",
            "commercial_use": True,
            "platforms": ["youtube", "tiktok"],
            "attribution": "No attribution required",
        },
    )
    assert rights.status_code == 201
    body = rights.json()
    assert body["status"] == "pending"
    approval_id = body["approval"]["id"]

    pending = client.get("/api/approvals?status=pending").json()
    assert any(record["id"] == approval_id for record in pending)

    approved = client.post(
        f"/api/approvals/{approval_id}/decision", json={"status": "approved"}
    )
    assert approved.status_code == 200
    assets = client.get("/api/assets").json()
    asset = next(item for item in assets if item["id"] == asset_id)
    assert asset["status"] == "rights_approved"
    assert asset["valid_rights"] is True


def test_asset_analysis_is_blocked_without_rights(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "blocked.mp4"
    source.write_bytes(b"not a real video")
    ingest = client.post("/api/assets/ingest", json={"path": str(source)})
    asset_id = ingest.json()["id"]
    analysis = client.post(f"/api/assets/{asset_id}/analyze")
    assert analysis.status_code == 403
    assert analysis.json()["code"] == "rights_blocked"


def test_emergency_stop_blocks_mutations_and_resume_restores(client: TestClient) -> None:
    stopped = client.post("/api/system/emergency-stop")
    assert stopped.status_code == 200
    assert stopped.json()["emergency_stop"] is True

    blocked = client.post("/api/tasks", json={"title": "blocked", "department": "production"})
    assert blocked.status_code == 423
    assert blocked.json()["code"] == "emergency_stop"

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["emergency_stop"] is True

    resumed = client.post("/api/system/resume")
    assert resumed.status_code == 200
    created = client.post("/api/tasks", json={"title": "allowed", "department": "production"})
    assert created.status_code == 201


def test_duplicate_ingest_is_rejected(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "duplicate.mp4"
    source.write_bytes(b"same bytes")
    first = client.post("/api/assets/ingest", json={"path": str(source)})
    second = client.post("/api/assets/ingest", json={"path": str(source)})
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


def test_upload_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/assets/upload",
        files={"file": ("upload.mp4", b"local upload bytes", "video/mp4")},
        data={"owner": "Founder"},
    )
    assert response.status_code == 201
    assert response.json()["owner"] == "Founder"
    assert response.json()["size_bytes"] == len(b"local upload bytes")
