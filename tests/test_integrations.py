from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.storage import store


def _insert_variant(*, qc: str = "passed", status: str = "qc_passed") -> str:
    variant_id = str(uuid.uuid4())
    store.insert(
        "video_variants",
        {
            "id": variant_id,
            "candidate_id": "candidate-fixture",
            "style": "reaction_first",
            "title": "Fixture reaction short",
            "script": "Fixture script",
            "caption_text": "Fixture caption",
            "qc_status": qc,
            "qc_report": {"passed": qc == "passed", "checks": {}},
            "status": status,
        },
    )
    return variant_id


def test_everygen_quote_approval_and_mock_job(
    client: TestClient, monkeypatch, sample_video: Path
) -> None:
    monkeypatch.setattr(settings, "everygen_enabled", True)
    quote = client.post(
        "/api/providers/everygen/quotes",
        json={"request": {"kind": "video", "duration_seconds": 10, "prompt": "fixture"}},
    )
    assert quote.status_code == 201, quote.text
    quote_body = quote.json()
    assert quote_body["credits"] == 60.0
    assert quote_body["cost_usd"] == 3.0
    assert quote_body["approval"]["status"] == "pending"

    early = client.post(
        "/api/providers/everygen/jobs", json={"quote_id": quote_body["id"]}
    )
    assert early.status_code == 403

    approved = client.post(
        f"/api/approvals/{quote_body['approval']['id']}/decision",
        json={"status": "approved"},
    )
    assert approved.status_code == 200

    job = client.post(
        "/api/providers/everygen/jobs", json={"quote_id": quote_body["id"]}
    )
    assert job.status_code == 202, job.text
    job_body = job.json()
    assert job_body["status"] == "queued"
    assert job_body["mock"] is True

    duplicate = client.post(
        "/api/providers/everygen/jobs", json={"quote_id": quote_body["id"]}
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True

    running = client.post(f"/api/providers/everygen/jobs/{job_body['id']}/poll")
    assert running.status_code == 200
    assert running.json()["status"] == "running"
    succeeded = client.post(f"/api/providers/everygen/jobs/{job_body['id']}/poll")
    assert succeeded.status_code == 200
    assert succeeded.json()["status"] == "succeeded"
    assert Path(succeeded.json()["result_uri"]).is_file()

    summary = client.get("/api/analytics/summary").json()
    assert summary["finance"]["provider_spend_usd"] == 3.0
    assert summary["finance"]["provider_remaining_usd"] == 22.0

    cancel = client.post(f"/api/providers/everygen/jobs/{job_body['id']}/cancel")
    assert cancel.status_code == 409


def test_everygen_budget_is_enforced(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "everygen_enabled", True)
    monkeypatch.setattr(settings, "everygen_budget_usd", 1.0)
    response = client.post(
        "/api/providers/everygen/quotes",
        json={"request": {"kind": "video", "duration_seconds": 10}},
    )
    assert response.status_code == 403
    assert "budget" in response.json()["detail"]


def test_mcp_registry_scoped_calls_and_high_risk_approval(client: TestClient) -> None:
    server = client.post(
        "/api/mcp/servers",
        json={
            "name": "fixture-server",
            "endpoint": "stdio://fixture",
            "transport": "stdio",
            "scopes": ["read"],
        },
    )
    assert server.status_code == 201, server.text
    server_id = server.json()["id"]
    assert client.post(f"/api/mcp/servers/{server_id}/connect").status_code == 200

    low = client.post(
        "/api/mcp/tools",
        json={"server_id": server_id, "name": "lookup", "risk": "low"},
    )
    assert low.status_code == 201
    call = client.post(
        "/api/mcp/tool-calls",
        json={"server_id": server_id, "tool_name": "lookup", "payload": {"q": "gta"}},
    )
    assert call.status_code == 201, call.text
    assert call.json()["status"] == "recorded"
    assert call.json()["output"]["mock"] is True

    high = client.post(
        "/api/mcp/tools",
        json={"server_id": server_id, "name": "delete_asset", "risk": "high"},
    )
    high_id = high.json()["id"]
    blocked = client.post(
        "/api/mcp/tool-calls",
        json={"server_id": server_id, "tool_name": "delete_asset", "payload": {}},
    )
    assert blocked.status_code == 403
    approval = client.post(
        "/api/approvals",
        json={"type": "mcp_tool", "subject_id": high_id, "reason": "fixture"},
    )
    approval_id = approval.json()["id"]
    client.post(f"/api/approvals/{approval_id}/decision", json={"status": "approved"})
    allowed = client.post(
        "/api/mcp/tool-calls",
        json={
            "server_id": server_id,
            "tool_name": "delete_asset",
            "payload": {},
            "approval_id": approval_id,
        },
    )
    assert allowed.status_code == 201
    missing = client.post(
        "/api/mcp/tool-calls",
        json={"server_id": server_id, "tool_name": "unknown", "payload": {}},
    )
    assert missing.status_code == 404


def test_cua_observe_draft_boundaries_and_tokens(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cua_enabled", True)
    request = client.post(
        "/api/cua/sessions",
        json={"target": "https://studio.youtube.com", "mode": "observe"},
    )
    assert request.status_code == 202, request.text
    session = request.json()
    assert session["status"] == "pending_approval"
    assert session["activation_required"] is True
    assert "capability_token" not in session

    premature = client.post(f"/api/cua/sessions/{session['id']}/activate")
    assert premature.status_code == 403

    approval_id = session["approval"]["id"]
    client.post(f"/api/approvals/{approval_id}/decision", json={"status": "approved"})
    activated = client.post(f"/api/cua/sessions/{session['id']}/activate")
    assert activated.status_code == 200, activated.text
    token = activated.json()["capability_token"]
    assert token

    action = client.post(
        f"/api/cua/sessions/{session['id']}/actions",
        json={
            "action_type": "screenshot",
            "target": "https://studio.youtube.com/studio",
            "result": {"ok": True},
            "token": token,
        },
    )
    assert action.status_code == 201, action.text
    assert Path(action.json()["evidence_uri"]).is_file()

    forbidden = client.post(
        f"/api/cua/sessions/{session['id']}/actions",
        json={"action_type": "fill", "target": None, "result": {}, "token": token},
    )
    assert forbidden.status_code == 403

    bad_token = client.post(
        f"/api/cua/sessions/{session['id']}/actions",
        json={"action_type": "read", "result": {}, "token": "wrong"},
    )
    assert bad_token.status_code == 403

    stopped = client.post(f"/api/cua/sessions/{session['id']}/stop")
    assert stopped.status_code == 200
    after_stop = client.post(
        f"/api/cua/sessions/{session['id']}/actions",
        json={"action_type": "read", "result": {}, "token": token},
    )
    assert after_stop.status_code == 403


def test_cua_domain_allowlist_and_action_limit(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cua_enabled", True)
    bad_domain = client.post(
        "/api/cua/sessions",
        json={"target": "https://evil.example.org", "mode": "observe"},
    )
    assert bad_domain.status_code == 403

    monkeypatch.setattr(settings, "cua_max_actions", 1)
    request = client.post(
        "/api/cua/sessions",
        json={"target": "https://youtube.com", "mode": "draft"},
    ).json()
    client.post(
        f"/api/approvals/{request['approval']['id']}/decision",
        json={"status": "approved"},
    )
    activated = client.post(f"/api/cua/sessions/{request['id']}/activate").json()
    token = activated["capability_token"]
    first = client.post(
        f"/api/cua/sessions/{request['id']}/actions",
        json={"action_type": "click", "result": {}, "token": token},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/cua/sessions/{request['id']}/actions",
        json={"action_type": "click", "result": {}, "token": token},
    )
    assert second.status_code == 403
    assert "limit" in second.json()["detail"]


def test_publishing_requires_both_approvals_and_is_dry_run(client: TestClient) -> None:
    variant_id = _insert_variant()
    blocked = client.post(
        "/api/publishing/jobs",
        json={"video_variant_id": variant_id, "platform": "youtube"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "approval_required"

    final = client.post(
        "/api/approvals",
        json={
            "type": "final_video",
            "subject_id": variant_id,
            "subject_type": "video_variant",
        },
    )
    client.post(f"/api/approvals/{final.json()['id']}/decision", json={"status": "approved"})

    job = client.post(
        "/api/publishing/jobs",
        json={"video_variant_id": variant_id, "platform": "youtube"},
    )
    assert job.status_code == 201, job.text
    job_body = job.json()
    duplicate = client.post(
        "/api/publishing/jobs",
        json={"video_variant_id": variant_id, "platform": "youtube"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True

    early = client.post(f"/api/publishing/jobs/{job_body['id']}/publish")
    assert early.status_code == 403

    client.post(
        f"/api/approvals/{job_body['approval']['id']}/decision",
        json={"status": "approved"},
    )
    published = client.post(f"/api/publishing/jobs/{job_body['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["post"]["status"] == "simulated"
    variant = client.get(f"/api/variants/{variant_id}").json()
    assert variant["status"] == "published"

    again = client.post(f"/api/publishing/jobs/{job_body['id']}/publish")
    assert again.status_code == 200
    assert again.json()["status"] == "published"

    reconcile = client.post(f"/api/publishing/jobs/{job_body['id']}/reconcile")
    assert reconcile.status_code == 200
    assert reconcile.json()["reconciled"] is True


def test_publishing_rejects_unapproved_qc(client: TestClient) -> None:
    variant_id = _insert_variant(qc="failed", status="qc_failed")
    final = client.post(
        "/api/approvals",
        json={"type": "final_video", "subject_id": variant_id},
    )
    client.post(f"/api/approvals/{final.json()['id']}/decision", json={"status": "approved"})
    job = client.post(
        "/api/publishing/jobs",
        json={"video_variant_id": variant_id, "platform": "youtube"},
    )
    assert job.status_code == 403
    assert "QC" in job.json()["detail"]
