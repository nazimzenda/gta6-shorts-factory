from __future__ import annotations

from fastapi.testclient import TestClient


def test_ceo_plan_creation_and_founder_acceptance(client: TestClient) -> None:
    response = client.post(
        "/api/ceo/instructions",
        json={"objective": "Produce three rights-cleared GTA 6 reaction shorts this week"},
    )
    assert response.status_code == 201, response.text
    initiative = response.json()
    assert initiative["status"] == "plan_pending"
    assert initiative["risk_level"] == "medium"
    assert len(initiative["tasks"]) == 12
    assert initiative["approval"]["status"] == "pending"
    assert all(task["status"] == "proposed" for task in initiative["tasks"])

    accepted = client.post(
        f"/api/initiatives/{initiative['id']}/decision",
        json={"decision": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["status"] == "active"
    assert any(task["status"] == "queued" for task in body["tasks"])
    assert body["approval"]["status"] == "approved"

    tick = client.post("/api/ceo/tick", json={"limit": 2})
    assert tick.status_code == 200, tick.text
    result = tick.json()
    assert result["run"] == 2
    completed = client.get("/api/tasks?status=completed").json()
    assert len(completed) >= 2
    report = client.get("/api/ceo/report").json()
    assert report["throughput"]["tasks_completed"] >= 2


def test_high_risk_objective_is_classified(client: TestClient) -> None:
    response = client.post(
        "/api/ceo/instructions",
        json={"objective": "Buy Everygen credits and run a paid promotion campaign"},
    )
    assert response.status_code == 201
    assert response.json()["risk_level"] == "high"


def test_rejected_plan_cancels_proposed_tasks(client: TestClient) -> None:
    initiative = client.post(
        "/api/ceo/instructions",
        json={"objective": "Test a new rights-cleared format"},
    ).json()
    rejected = client.post(
        f"/api/initiatives/{initiative['id']}/decision",
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert all(task["status"] == "cancelled" for task in rejected.json()["tasks"])


def test_department_interaction_map_reflects_task_dependencies(client: TestClient) -> None:
    baseline = client.get("/api/departments/interactions")
    assert baseline.status_code == 200, baseline.text
    body = baseline.json()
    assert len(body["nodes"]) == 7
    assert any(
        edge["source"] == "research" and edge["target"] == "creative"
        for edge in body["edges"]
    )
    assert body["summary"]["departments"] == 7

    initiative = client.post(
        "/api/ceo/instructions",
        json={"objective": "Map cross-department handoffs for a rights-cleared short"},
    ).json()
    client.post(
        f"/api/initiatives/{initiative['id']}/decision",
        json={"decision": "accepted"},
    )
    tick = client.post("/api/ceo/tick", json={"limit": 3})
    assert tick.status_code == 200, tick.text

    interactions = client.get("/api/departments/interactions").json()
    assert interactions["handoffs"]
    assert interactions["summary"]["cross_department_links"] > 0
    assert interactions["summary"]["active_handoffs"] > 0
    assert any(node["outgoing"] > 0 for node in interactions["nodes"])
    assert any(node["incoming"] > 0 for node in interactions["nodes"])


def test_task_retry_and_dead_letter_flow(client: TestClient) -> None:
    task = client.post(
        "/api/tasks",
        json={
            "title": "Analyze missing asset",
            "department": "production",
            "type": "analysis",
            "input_ref": "missing-asset-id",
        },
    ).json()
    task_id = task["id"]
    first = client.post(f"/api/tasks/{task_id}/run")
    assert first.status_code == 200
    assert first.json()["status"] == "retry"
    assert first.json()["attempts"] == 1

    retried = client.post(f"/api/tasks/{task_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0

    second = client.post(f"/api/tasks/{task_id}/run")
    assert second.json()["status"] == "retry"


def test_department_pause_blocks_task_execution(client: TestClient) -> None:
    task = client.post(
        "/api/tasks",
        json={"title": "Research pause test", "department": "research", "type": "research"},
    ).json()
    paused = client.post(
        "/api/departments/research/pause", json={"paused": True}
    )
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    blocked = client.post(f"/api/tasks/{task['id']}/run")
    assert blocked.status_code == 403
    resumed = client.post("/api/departments/research/pause", json={"paused": False})
    assert resumed.status_code == 200
    run = client.post(f"/api/tasks/{task['id']}/run")
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
