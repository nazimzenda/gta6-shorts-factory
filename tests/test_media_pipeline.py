from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _approved_asset(client: TestClient, path: Path) -> str:
    ingest = client.post(
        "/api/assets/ingest",
        json={"path": str(path), "owner": "Founder", "source_url": "local://fixture"},
    )
    assert ingest.status_code == 201, ingest.text
    asset_id = ingest.json()["id"]
    rights = client.post(
        "/api/rights",
        json={
            "source_asset_id": asset_id,
            "owner": "Founder",
            "license_type": "owned",
            "commercial_use": True,
            "platforms": ["youtube", "tiktok"],
            "proof_uri": "local://rights/fixture",
        },
    )
    assert rights.status_code == 201, rights.text
    approval_id = rights.json()["approval"]["id"]
    decision = client.post(
        f"/api/approvals/{approval_id}/decision",
        json={"status": "approved", "note": "owned fixture"},
    )
    assert decision.status_code == 200, decision.text
    return asset_id


def test_full_local_media_pipeline_and_dry_run_publish(
    client: TestClient, sample_video: Path
) -> None:
    asset_id = _approved_asset(client, sample_video)

    analysis = client.post(f"/api/assets/{asset_id}/analyze")
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["transcript"]["status"] in {"unavailable", "ready", "error"}
    assert body["candidates"]
    candidate = body["candidates"][0]
    assert candidate["score"] > 0
    assert body["asset"]["status"] == "analyzed"

    variants = client.post(
        f"/api/candidates/{candidate['id']}/variants", json={}
    )
    assert variants.status_code == 201, variants.text
    drafts = variants.json()
    assert len(drafts) == 5
    assert len({draft["style"] for draft in drafts}) == 5
    variant_id = drafts[0]["id"]

    render = client.post(f"/api/variants/{variant_id}/render", json={})
    assert render.status_code == 200, render.text
    rendered = render.json()["variant"]
    assert Path(rendered["render_uri"]).is_file()
    assert rendered["status"] == "rendered"

    file_response = client.get(f"/api/variants/{variant_id}/file")
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "video/mp4"
    assert len(file_response.content) > 10_000

    caption_response = client.get(f"/api/variants/{variant_id}/captions")
    assert caption_response.status_code == 200
    assert "-->" in caption_response.text

    qc = client.post(f"/api/variants/{variant_id}/qc")
    assert qc.status_code == 200, qc.text
    qc_body = qc.json()
    assert qc_body["qc_status"] == "passed"
    assert qc_body["qc_report"]["checks"]["vertical"]["passed"] is True
    assert qc_body["qc_report"]["checks"]["audio"]["passed"] is True

    review = client.post(f"/api/variants/{variant_id}/submit-review")
    assert review.status_code == 200, review.text
    final_approval = review.json()["approval"]
    assert final_approval["status"] == "pending"

    approved = client.post(
        f"/api/approvals/{final_approval['id']}/decision",
        json={"status": "approved", "note": "founder reviewed final cut"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    job = client.post(
        "/api/publishing/jobs",
        json={"video_variant_id": variant_id, "platform": "youtube"},
    )
    assert job.status_code == 201, job.text
    job_body = job.json()
    assert job_body["status"] == "pending_approval"
    publish_approval = job_body["approval"]["id"]

    publish_too_early = client.post(f"/api/publishing/jobs/{job_body['id']}/publish")
    assert publish_too_early.status_code == 403

    decided = client.post(
        f"/api/approvals/{publish_approval}/decision",
        json={"status": "approved", "note": "schedule approved"},
    )
    assert decided.status_code == 200

    published = client.post(f"/api/publishing/jobs/{job_body['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["post"]["status"] == "simulated"

    post_id = published.json()["post"]["id"]
    snapshot = client.post(
        "/api/analytics/snapshots",
        json={
            "platform_post_id": post_id,
            "views": 1200,
            "likes": 88,
            "comments": 7,
            "shares": 4,
            "follows": 9,
            "retention": 61.5,
            "watch_time": 820,
        },
    )
    assert snapshot.status_code == 201, snapshot.text

    summary = client.get("/api/analytics/summary").json()
    assert summary["publishing"]["posts"] == 1
    assert summary["publishing"]["views"] == 1200
    assert summary["publishing"]["average_retention"] == 61.5
    assert summary["finance"]["total_cost_usd"] >= 0

    daily = client.get("/api/reports/daily").json()
    assert daily["posts_created"] == 1
    weekly = client.get("/api/reports/weekly").json()
    assert weekly["posts_created"] == 1


def test_render_is_reused_without_force(client: TestClient, sample_video: Path) -> None:
    asset_id = _approved_asset(client, sample_video)
    candidate = client.post(f"/api/assets/{asset_id}/analyze").json()["candidates"][0]
    variant = client.post(f"/api/candidates/{candidate['id']}/variants", json={}).json()[0]
    first = client.post(f"/api/variants/{variant['id']}/render", json={})
    assert first.status_code == 200
    second = client.post(f"/api/variants/{variant['id']}/render", json={})
    assert second.status_code == 200
    assert second.json()["reused"] is True


def test_qc_rejects_variant_without_render(client: TestClient, sample_video: Path) -> None:
    asset_id = _approved_asset(client, sample_video)
    candidate = client.post(f"/api/assets/{asset_id}/analyze").json()["candidates"][0]
    variant = client.post(f"/api/candidates/{candidate['id']}/variants", json={}).json()[0]
    qc = client.post(f"/api/variants/{variant['id']}/qc")
    assert qc.status_code == 200
    assert qc.json()["qc_status"] == "failed"
    review = client.post(f"/api/variants/{variant['id']}/submit-review")
    assert review.status_code == 403
