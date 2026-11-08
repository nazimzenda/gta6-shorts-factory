from __future__ import annotations

from typing import Any

from app.services import FactoryService
from app.storage import Store

# The operating model from the brief. These edges are always visible so the
# founder can see the intended flow even before any work has run.
BASELINE_EDGES: list[tuple[str, str, str, str]] = [
    ("research", "creative", "research brief & rights signal", "flow"),
    ("research", "production", "approved source + provenance", "flow"),
    ("creative", "production", "hook, script & caption plan", "flow"),
    ("production", "publishing", "QC-passed master + SRT", "flow"),
    ("publishing", "analytics", "post IDs, schedule & status", "flow"),
    ("analytics", "creative", "retention & style learning", "feedback"),
    ("analytics", "research", "topic performance feedback", "feedback"),
    ("engineering", "production", "pipeline, render & probe tools", "support"),
    ("engineering", "publishing", "adapter & policy checks", "support"),
    ("operations", "production", "queue health, cost & backup", "support"),
    ("operations", "publishing", "schedule & budget oversight", "support"),
    ("operations", "research", "rights evidence archive", "support"),
]

ACTIVE_TARGET_STATUSES = {"queued", "running", "retry", "waiting_approval", "pending"}
COMPLETED_STATUS = "completed"


class CollaborationService:
    """Computes the live department dependency graph from tasks and events."""

    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    def interaction_map(self) -> dict[str, Any]:
        departments = self.service.list_departments(include_workers=True)
        nodes: dict[str, dict[str, Any]] = {}
        for department in departments:
            nodes[department["id"]] = {
                "id": department["id"],
                "name": department["name"],
                "status": department["status"],
                "paused": department.get("paused", False),
                "manager": department.get("manager"),
                "worker_count": department.get("worker_count", 0),
                "active_workers": department.get("active_worker_count", 0),
                "open_tasks": department.get("open_tasks", 0),
                "completed_tasks": department.get("completed_tasks", 0),
                "incoming": 0,
                "outgoing": 0,
                "load": department.get("open_tasks", 0),
            }

        edges: dict[tuple[str, str], dict[str, Any]] = {}
        for source, target, label, kind in BASELINE_EDGES:
            if source in nodes and target in nodes:
                edges[(source, target)] = {
                    "source": source,
                    "target": target,
                    "label": label,
                    "kind": kind,
                    "count": 0,
                    "completed": 0,
                    "active": 0,
                    "pending": 0,
                    "baseline": True,
                }

        dependencies = self.repository.many(
            """
            SELECT d.depends_on_task_id, t.id AS task_id, t.title, t.department AS target,
                   t.status AS target_status, t.worker, t.updated_at,
                   dt.department AS source, dt.title AS source_title,
                   dt.status AS source_status
            FROM task_dependencies d
            JOIN tasks t ON t.id = d.task_id
            JOIN tasks dt ON dt.id = d.depends_on_task_id
            WHERE t.department != dt.department
            ORDER BY t.updated_at DESC, t.rowid DESC
            """,
            (),
            "",
        )
        for row in dependencies:
            source = row["source"]
            target = row["target"]
            if source not in nodes or target not in nodes:
                continue
            edge = edges.setdefault(
                (source, target),
                {
                    "source": source,
                    "target": target,
                    "label": "task dependency",
                    "kind": "flow",
                    "count": 0,
                    "completed": 0,
                    "active": 0,
                    "pending": 0,
                    "baseline": False,
                },
            )
            edge["count"] += 1
            source_status = row["source_status"]
            target_status = row["target_status"]
            if source_status == COMPLETED_STATUS and target_status == COMPLETED_STATUS:
                edge["completed"] += 1
            elif source_status == COMPLETED_STATUS and target_status in ACTIVE_TARGET_STATUSES:
                edge["active"] += 1
            elif source_status == COMPLETED_STATUS:
                edge["active"] += 1
            else:
                edge["pending"] += 1

        for edge in edges.values():
            if edge["source"] in nodes:
                nodes[edge["source"]]["outgoing"] += edge["count"]
            if edge["target"] in nodes:
                nodes[edge["target"]]["incoming"] += edge["count"]

        handoffs = []
        for row in dependencies[:12]:
            if row["source"] not in nodes or row["target"] not in nodes:
                continue
            handoffs.append(
                {
                    "id": row["task_id"],
                    "title": row["title"],
                    "depends_on": row["source_title"],
                    "source": row["source"],
                    "source_name": nodes[row["source"]]["name"],
                    "target": row["target"],
                    "target_name": nodes[row["target"]]["name"],
                    "source_status": row["source_status"],
                    "target_status": row["target_status"],
                    "worker": row["worker"],
                    "updated_at": row["updated_at"],
                }
            )

        bus = self.repository.many(
            """
            SELECT te.event_type, te.actor, te.occurred_at, t.title, t.department,
                   t.status AS task_status
            FROM task_events te
            JOIN tasks t ON t.id = te.task_id
            ORDER BY te.id DESC
            LIMIT 15
            """,
            (),
            "",
        )
        for event in bus:
            event["department_name"] = (
                nodes.get(event["department"], {}).get("name", event["department"])
            )

        edge_list = sorted(
            edges.values(),
            key=lambda edge: (edge["active"], edge["count"], edge["completed"]),
            reverse=True,
        )
        active_handoffs = sum(edge["active"] for edge in edge_list)
        completed_handoffs = sum(edge["completed"] for edge in edge_list)
        pending_handoffs = sum(edge["pending"] for edge in edge_list)
        linked_edges = [edge for edge in edge_list if edge["count"] > 0]
        bottleneck = max(
            nodes.values(), key=lambda node: node["load"], default=None
        )
        if bottleneck and bottleneck["load"] == 0:
            bottleneck = None
        busiest = max(linked_edges, key=lambda edge: edge["count"], default=None)

        return {
            "generated_at": self.repository.one(
                "SELECT CURRENT_TIMESTAMP AS now", (), ""
            )["now"],
            "nodes": list(nodes.values()),
            "edges": edge_list,
            "handoffs": handoffs,
            "bus": bus,
            "summary": {
                "departments": len(nodes),
                "cross_department_links": len(linked_edges),
                "active_handoffs": active_handoffs,
                "completed_handoffs": completed_handoffs,
                "pending_handoffs": pending_handoffs,
                "queued_tasks": self.repository.count(
                    "tasks", "status IN ('queued','retry','running')"
                ),
                "bottleneck": bottleneck,
                "busiest_edge": busiest,
            },
        }
