from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_detail_reports_safe_defaults(client: TestClient) -> None:
    response = client.get("/health/detail")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["emergency_stop"] is False
    assert body["flags"]["everygen"] is False
    assert body["flags"]["cua"] is False
    assert body["flags"]["publishing_dry_run"] is True


def test_dashboard_defaults_and_org_structure(client: TestClient) -> None:
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "GTA 6 Shorts Factory"
    assert body["local_processing_enabled"] is True
    assert body["everygen_enabled"] is False
    assert body["cua_enabled"] is False
    assert body["emergency_stop"] is False
    assert body["workers_total"] >= 30
    assert body["active_workers"] == body["workers_total"]
    assert request_id(body["recent_activity"]) is not None


def request_id(events: list[dict]) -> int | None:
    return events[0]["id"] if events else None


def test_founder_control_tower_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "FOUNDER CONTROL TOWER" in response.text
    assert "/static/app.js" in response.text
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_departments_and_workers(client: TestClient) -> None:
    departments = client.get("/api/departments").json()
    assert len(departments) == 7
    assert all(department["workers"] for department in departments)
    workers = client.get("/api/workers").json()
    assert len(workers) >= 30
    rights_officer = next(worker for worker in workers if worker["id"] == "rights-officer")
    assert "manage_rights" in rights_officer["permissions"]


def test_live_dashboard_socket(client: TestClient) -> None:
    with client.websocket_connect("/ws/dashboard") as websocket:
        update = websocket.receive_json()
        assert update["type"] == "summary"
        assert update["company_name"] == "GTA 6 Shorts Factory"
        assert "pending_approvals" in update
