from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.errors import (
    Conflict,
    FactoryError,
    NotFound,
    PolicyError,
    RightsError,
    ValidationProblem,
)
from app.policy import require_running
from app.services import FactoryService
from app.storage import Store

PLAN_STEPS: list[dict[str, Any]] = [
    {
        "key": "research",
        "title": "Research current GTA 6 clip opportunities and source options",
        "department": "research",
        "type": "research",
        "priority": 1,
        "capability": "trend_scan",
    },
    {
        "key": "rights_review",
        "title": "Verify rights evidence for every candidate source",
        "department": "research",
        "type": "rights_review",
        "priority": 1,
        "capability": "rights_review",
        "depends_on": ["research"],
    },
    {
        "key": "creative",
        "title": "Draft hooks, scripts, covers, and metadata angles",
        "department": "creative",
        "type": "creative",
        "priority": 2,
        "capability": "hook_writing",
        "depends_on": ["research"],
    },
    {
        "key": "ingest",
        "title": "Ingest rights-cleared source footage",
        "department": "production",
        "type": "ingest",
        "priority": 1,
        "capability": "ingest",
        "depends_on": ["rights_review"],
    },
    {
        "key": "analysis",
        "title": "Analyze highlights and propose candidate moments",
        "department": "production",
        "type": "analysis",
        "priority": 1,
        "capability": "highlight_detection",
        "depends_on": ["ingest"],
    },
    {
        "key": "variants",
        "title": "Create materially different vertical drafts",
        "department": "production",
        "type": "variants",
        "priority": 2,
        "capability": "vertical_edit",
        "depends_on": ["analysis", "creative"],
    },
    {
        "key": "render",
        "title": "Render 9:16 variants locally",
        "department": "production",
        "type": "render",
        "priority": 2,
        "capability": "render_video",
        "depends_on": ["variants"],
    },
    {
        "key": "qc",
        "title": "Run automated quality control on rendered variants",
        "department": "production",
        "type": "qc",
        "priority": 2,
        "capability": "qc_decode",
        "depends_on": ["render"],
    },
    {
        "key": "publish_prep",
        "title": "Prepare platform metadata and complete policy check",
        "department": "publishing",
        "type": "publish_prep",
        "priority": 3,
        "capability": "platform_policy_check",
        "depends_on": ["qc"],
    },
    {
        "key": "analytics",
        "title": "Define success metrics and the first experiment",
        "department": "analytics",
        "type": "analytics",
        "priority": 3,
        "capability": "experiment_design",
        "depends_on": ["publish_prep"],
    },
    {
        "key": "engineering",
        "title": "Confirm pipeline, MCP, and integration readiness",
        "department": "engineering",
        "type": "engineering",
        "priority": 3,
        "capability": "pipeline_build",
    },
    {
        "key": "operations",
        "title": "Confirm queue, cost, and backup readiness",
        "department": "operations",
        "type": "operations",
        "priority": 3,
        "capability": "queue_monitor",
    },
]


class CEOOrchestrator:
    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    # -------------------------------------------------------------- initiatives
    def create_initiative(
        self, objective: str, *, risk_level: str | None = None
    ) -> dict[str, Any]:
        require_running(self.repository)
        objective = objective.strip()
        if not objective:
            raise ValidationProblem("a strategic objective is required")
        business = self.repository.one("SELECT * FROM businesses ORDER BY created_at ASC LIMIT 1", (), "businesses")
        if not business:
            raise NotFound("no business is configured")
        risk = risk_level or self._infer_risk(objective)
        if risk not in {"low", "medium", "high"}:
            raise ValidationProblem("risk_level must be low, medium, or high")
        initiative_id = str(uuid.uuid4())
        plan = {
            "objective": objective,
            "risk_level": risk,
            "rationale": self._rationale(objective, risk),
            "steps": [
                {
                    "key": step["key"],
                    "title": step["title"],
                    "department": step["department"],
                    "type": step["type"],
                    "depends_on": step.get("depends_on", []),
                }
                for step in PLAN_STEPS
            ],
            "approval_policy": "Founder accepts the plan before department queues start.",
        }
        self.repository.insert(
            "initiatives",
            {
                "id": initiative_id,
                "business_id": business["id"],
                "objective": objective,
                "status": "plan_pending",
                "risk_level": risk,
                "plan": plan,
            },
        )
        task_by_key: dict[str, dict[str, Any]] = {}
        for step in PLAN_STEPS:
            worker = self._pick_worker(step["department"], step["capability"])
            task = self.service.create_task(
                step["title"],
                step["department"],
                worker["name"] if worker else None,
                initiative_id=initiative_id,
                task_type=step["type"],
                priority=step["priority"],
                status="proposed",
            )
            if worker:
                self.repository.update("tasks", task["id"], {"worker_id": worker["id"]})
            task_by_key[step["key"]] = task
        for step in PLAN_STEPS:
            for dependency_key in step.get("depends_on", []):
                dependency = task_by_key.get(dependency_key)
                if dependency:
                    self.repository.execute(
                        "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) "
                        "VALUES (?, ?)",
                        (task_by_key[step["key"]]["id"], dependency["id"]),
                    )
        approval = self.service.create_approval(
            "initiative_plan",
            initiative_id,
            subject_type="initiative",
            requested_by="ceo",
            reason=f"Approve plan for: {objective}",
        )
        self.repository.audit(
            "ceo",
            "initiative_created",
            initiative_id,
            {"risk_level": risk, "tasks": len(task_by_key), "approval_id": approval["id"]},
        )
        return self.get_initiative(initiative_id)

    @staticmethod
    def _infer_risk(objective: str) -> str:
        lowered = objective.lower()
        high_terms = {"paid", "spend", "buy", "credit", "everygen", "promotion", "ad budget"}
        medium_terms = {"publish", "post", "rights", "creator", "source", "partner", "tiktok", "youtube"}
        if any(term in lowered for term in high_terms):
            return "high"
        if any(term in lowered for term in medium_terms):
            return "medium"
        return "low"

    @staticmethod
    def _rationale(objective: str, risk: str) -> str:
        return (
            f"The CEO decomposed '{objective}' into a rights-gated production plan. "
            f"Risk is assessed as {risk}; no paid provider call or final publish can occur "
            "without a separate founder approval record."
        )

    def _pick_worker(self, department: str, capability: str) -> dict[str, Any] | None:
        workers = self.repository.many(
            "SELECT * FROM workers WHERE department_id = ? AND status = 'active' "
            "ORDER BY created_at ASC",
            (department,),
            "workers",
        )
        for worker in workers:
            if capability in (worker.get("capabilities") or []):
                return worker
        return workers[0] if workers else None

    def list_initiatives(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE status = ?" if status else ""
        params = (status,) if status else ()
        rows = self.repository.many(
            f"SELECT * FROM initiatives {where} ORDER BY created_at DESC",
            params,
            "initiatives",
        )
        for row in rows:
            row["task_counts"] = {
                task["status"]: task["count"]
                for task in self.repository.many(
                    "SELECT status, COUNT(*) AS count FROM tasks WHERE initiative_id = ? "
                    "GROUP BY status",
                    (row["id"],),
                    "",
                )
            }
            row["approval"] = self.repository.one(
                "SELECT * FROM approvals WHERE type = 'initiative_plan' AND subject_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (row["id"],),
                "approvals",
            )
        return rows

    def get_initiative(self, initiative_id: str) -> dict[str, Any]:
        row = self.repository.one(
            "SELECT * FROM initiatives WHERE id = ?", (initiative_id,), "initiatives"
        )
        if not row:
            raise NotFound("initiative not found")
        row["tasks"] = self.service.list_tasks(initiative_id=initiative_id)
        row["approval"] = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'initiative_plan' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (initiative_id,),
            "approvals",
        )
        return row

    def decide_initiative(self, initiative_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"accepted", "rejected"}:
            raise ValidationProblem("decision must be accepted or rejected")
        initiative = self.get_initiative(initiative_id)
        if initiative["status"] != "plan_pending":
            raise Conflict("initiative plan has already been decided")
        approval = initiative.get("approval")
        if approval and approval["status"] == "pending":
            self.service.decide_approval(
                approval["id"],
                "approved" if decision == "accepted" else "rejected",
                note=f"Founder {decision} the CEO plan",
            )
        else:
            status = "active" if decision == "accepted" else "rejected"
            self.repository.update("initiatives", initiative_id, {"status": status})
            self.repository.execute(
                "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE initiative_id = ? AND status = 'proposed'",
                ("queued" if decision == "accepted" else "cancelled", initiative_id),
            )
            self.repository.audit("founder", f"initiative_{decision}", initiative_id)
        return self.get_initiative(initiative_id)

    # ----------------------------------------------------------------- execution
    def run_task(self, task_id: str, actor: str = "ceo") -> dict[str, Any]:
        require_running(self.repository)
        task = self.service.get_task(task_id)
        if task["status"] not in {"queued", "pending", "retry"}:
            raise Conflict(f"task is {task['status']} and cannot run")
        paused = set(self.repository.get_state("paused_departments", []))
        if task["department"] in paused:
            raise PolicyError(f"department {task['department']} is paused")
        blocking = self._blocking_dependencies(task_id)
        if blocking:
            raise Conflict(f"task dependencies are incomplete: {', '.join(blocking)}")
        worker = None
        if task.get("worker_id"):
            worker = self.repository.one(
                "SELECT * FROM workers WHERE id = ?", (task["worker_id"],), "workers"
            )
            if worker and worker["status"] == "paused":
                raise PolicyError(f"worker {worker['name']} is paused")

        attempts = int(task.get("attempts") or 0) + 1
        self.repository.execute(
            "UPDATE tasks SET status = 'running', attempts = ?, started_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (attempts, task_id),
        )
        if worker:
            self.repository.execute(
                "UPDATE workers SET current_task_id = ?, last_action = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (task_id, task["title"], worker["id"]),
            )
        self.service.task_event(task_id, "started", {"attempt": attempts}, actor)

        try:
            output = self._execute(task, actor)
        except (FactoryError, FileNotFoundError, ValueError, PermissionError, RuntimeError) as error:
            message = str(error)
            will_retry = attempts < int(task.get("max_attempts") or 3)
            new_status = "retry" if will_retry else "dead_letter"
            self.repository.execute(
                "UPDATE tasks SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_status, message, task_id),
            )
            self.service.task_event(
                task_id,
                "failed" if not will_retry else "retry_scheduled",
                {"attempt": attempts, "error": message},
                actor,
            )
            self.repository.audit(
                actor,
                "task_failed" if not will_retry else "task_retry",
                task_id,
                {"error": message, "attempt": attempts},
            )
            if worker:
                self.repository.execute(
                    "UPDATE workers SET current_task_id = NULL, last_action = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (f"Task failed: {message[:120]}", worker["id"]),
                )
            result = self.service.get_task(task_id)
            result["success"] = False
            return result

        self.repository.execute(
            "UPDATE tasks SET status = 'completed', output_ref = ?, evidence = ?, error = NULL, "
            "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (
                output.get("output_ref"),
                json.dumps(output.get("evidence", {}), sort_keys=True),
                task_id,
            ),
        )
        self.service.task_event(task_id, "completed", output, actor)
        self.repository.audit(actor, "task_completed", task_id, {"type": task["type"]})
        if worker:
            self.repository.execute(
                "UPDATE workers SET current_task_id = NULL, last_action = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (f"Completed: {task['title']}", worker["id"]),
            )
        result = self.service.get_task(task_id)
        result["success"] = True
        return result

    def _blocking_dependencies(self, task_id: str) -> list[str]:
        dependencies = self.repository.many(
            "SELECT t.id, t.title, t.status FROM task_dependencies d "
            "JOIN tasks t ON t.id = d.depends_on_task_id WHERE d.task_id = ?",
            (task_id,),
            "tasks",
        )
        return [
            dependency["title"]
            for dependency in dependencies
            if dependency["status"] != "completed"
        ]

    def _execute(self, task: dict[str, Any], actor: str) -> dict[str, Any]:
        task_type = task["type"]
        input_ref = task.get("input_ref")
        if task_type == "ingest":
            if not input_ref:
                return self._simulated(
                    task,
                    "Ingest worker is ready; attach a local file path to this task to ingest.",
                )
            asset = self.service.media.register_asset(input_ref, owner="founder")
            return {
                "output_ref": asset["id"],
                "evidence": {
                    "kind": "asset",
                    "sha256": asset.get("sha256"),
                    "duration": asset.get("duration"),
                    "rights_status": asset.get("status"),
                },
            }
        if task_type == "analysis":
            if not input_ref:
                return self._simulated(task, "Attach an approved source asset id for analysis.")
            result = self.service.media.analyze_asset(input_ref, refresh=True)
            candidates = result["candidates"]
            return {
                "output_ref": candidates[0]["id"] if candidates else None,
                "evidence": {
                    "kind": "analysis",
                    "candidates": len(candidates),
                    "transcript_status": result["transcript"].get("status"),
                    "top_score": candidates[0]["score"] if candidates else None,
                },
            }
        if task_type == "variants":
            if not input_ref:
                return self._simulated(task, "Attach a candidate id to create creative variants.")
            variants = self.service.media.create_variants(input_ref)
            return {
                "output_ref": variants[0]["id"] if variants else None,
                "evidence": {
                    "kind": "creative_package",
                    "variants": [variant["style"] for variant in variants],
                },
            }
        if task_type == "render":
            if not input_ref:
                return self._simulated(task, "Attach a variant id to render a vertical cut.")
            result = self.service.media.render_variant(input_ref)
            variant = result["variant"]
            return {
                "output_ref": variant["id"],
                "evidence": {
                    "kind": "render",
                    "uri": variant.get("render_uri"),
                    "reused": result.get("reused"),
                },
            }
        if task_type == "qc":
            if not input_ref:
                return self._simulated(task, "Attach a rendered variant id to run QC.")
            variant = self.service.media.qc_variant(input_ref)
            return {
                "output_ref": variant["id"],
                "evidence": {
                    "kind": "qc",
                    "qc_status": variant["qc_status"],
                    "report": variant.get("qc_report"),
                },
            }
        return self._simulated(task, self._simulated_note(task_type))

    def _simulated(self, task: dict[str, Any], note: str) -> dict[str, Any]:
        return {
            "output_ref": f"evidence:{task['id']}",
            "evidence": {
                "kind": "department_evidence",
                "task_type": task["type"],
                "department": task["department"],
                "note": note,
                "risk": "No external action was taken.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    @staticmethod
    def _simulated_note(task_type: str) -> str:
        notes = {
            "research": "Research brief recorded. Source rights still require evidence.",
            "rights_review": "Rights review checklist recorded; approval remains with the founder.",
            "creative": "Creative treatment and hook options recorded for review.",
            "publish_prep": "Metadata draft and policy checklist recorded; publishing remains blocked.",
            "analytics": "Success metrics and experiment hypothesis recorded.",
            "engineering": "Pipeline and integration checklist recorded.",
            "operations": "Queue, cost, and backup checklist recorded.",
        }
        return notes.get(task_type, "Department evidence recorded.")

    def tick(self, limit: int = 5) -> dict[str, Any]:
        require_running(self.repository)
        candidates = self.repository.many(
            "SELECT id FROM tasks WHERE status IN ('queued','retry') "
            "ORDER BY priority ASC, rowid ASC LIMIT ?",
            (max(1, min(limit, 25)),),
            "tasks",
        )
        results = []
        for row in candidates:
            try:
                results.append(self.run_task(row["id"]))
            except (Conflict, PolicyError) as error:
                results.append({"id": row["id"], "skipped": True, "reason": str(error)})
        return {
            "run": len([result for result in results if not result.get("skipped")]),
            "skipped": len([result for result in results if result.get("skipped")]),
            "results": results,
        }

    def retry_task(self, task_id: str) -> dict[str, Any]:
        task = self.service.get_task(task_id)
        if task["status"] not in {"failed", "dead_letter", "retry"}:
            raise Conflict("only failed, retry, or dead-letter tasks can be retried")
        self.repository.update(
            "tasks", task_id, {"status": "queued", "error": None, "attempts": 0}
        )
        self.service.task_event(task_id, "retry_requested", {}, "founder")
        self.repository.audit("founder", "task_retry_requested", task_id)
        return self.service.get_task(task_id)
