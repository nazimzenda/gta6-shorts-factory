from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.errors import ApprovalRequired, Conflict, NotFound, PolicyError
from app.media import MediaPipeline, media_tools
from app.policy import APPROVAL_TYPES, HIGH_RISK_CAPABILITIES, is_expired, require_approval
from app.storage import Store


class FactoryService:
    """Founder-facing enterprise operations: people, work, rights, and approvals."""

    def __init__(self, repository: Store) -> None:
        self.repository = repository
        self.media = MediaPipeline(repository)

    # --------------------------------------------------------------- approvals
    def create_approval(
        self,
        approval_type: str,
        subject_id: str,
        *,
        subject_type: str | None = None,
        requested_by: str = "ceo",
        reason: str | None = None,
    ) -> dict[str, Any]:
        if not approval_type or not subject_id:
            raise ValueError("approval type and subject_id are required")
        if approval_type not in APPROVAL_TYPES:
            raise ValueError(f"unsupported approval type: {approval_type}")
        approval_id = str(uuid.uuid4())
        row = self.repository.insert(
            "approvals",
            {
                "id": approval_id,
                "type": approval_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "requested_by": requested_by,
                "status": "pending",
                "reason": reason,
            },
        )
        self.repository.audit(
            requested_by,
            "approval_requested",
            approval_id,
            {"type": approval_type, "subject_id": subject_id, "reason": reason},
        )
        return row

    def list_approvals(
        self, status: str | None = None, approval_type: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if approval_type:
            clauses.append("type = ?")
            params.append(approval_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.repository.many(
            f"SELECT * FROM approvals {where} ORDER BY created_at DESC", params, "approvals"
        )
        for row in rows:
            row["subject"] = self._approval_subject(row)
        return rows

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.repository.one(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,), "approvals"
        )
        if not row:
            raise NotFound("approval not found")
        row["subject"] = self._approval_subject(row)
        return row

    def _approval_subject(self, approval: dict[str, Any]) -> dict[str, Any] | None:
        approval_type = approval.get("type")
        subject_id = approval.get("subject_id")
        if not subject_id:
            return None
        if approval_type == "rights":
            return self.repository.one(
                "SELECT * FROM rights_records WHERE id = ?", (subject_id,), "rights_records"
            )
        if approval_type == "final_video":
            return self.repository.one(
                "SELECT id, style, title, qc_status, status FROM video_variants WHERE id = ?",
                (subject_id,),
                "video_variants",
            )
        if approval_type == "provider_quote":
            return self.repository.one(
                "SELECT * FROM provider_quotes WHERE id = ?", (subject_id,), "provider_quotes"
            )
        if approval_type == "publish_final":
            return self.repository.one(
                "SELECT * FROM publishing_jobs WHERE id = ?", (subject_id,), "publishing_jobs"
            )
        if approval_type == "cua_session":
            return self.repository.one(
                "SELECT * FROM cua_sessions WHERE id = ?", (subject_id,), "cua_sessions"
            )
        if approval_type == "initiative_plan":
            return self.repository.one(
                "SELECT * FROM initiatives WHERE id = ?", (subject_id,), "initiatives"
            )
        if approval_type == "mcp_tool":
            return self.repository.one(
                "SELECT * FROM mcp_tools WHERE id = ?", (subject_id,), "mcp_tools"
            )
        return None

    def decide_approval(
        self,
        approval_id: str,
        status: str,
        *,
        decided_by: str = "founder",
        note: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        existing = self.repository.one(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,), "approvals"
        )
        if not existing:
            raise NotFound("approval not found")
        if existing["status"] == status:
            return self.get_approval(approval_id)
        if existing["status"] != "pending":
            raise Conflict("approval has already been decided")
        self.repository.update(
            "approvals",
            approval_id,
            {
                "status": status,
                "decided_by": decided_by,
                "decided_at": None,
                "reason": note or existing.get("reason"),
            },
        )
        self.repository.execute(
            "UPDATE approvals SET decided_at = CURRENT_TIMESTAMP WHERE id = ?", (approval_id,)
        )
        self._apply_decision(existing, status)
        self.repository.audit(
            decided_by,
            f"approval_{status}",
            approval_id,
            {"type": existing["type"], "subject_id": existing["subject_id"], "note": note},
            approval_id,
        )
        return self.get_approval(approval_id)

    def _apply_decision(self, approval: dict[str, Any], status: str) -> None:
        approval_type = approval["type"]
        subject_id = approval["subject_id"]
        if approval_type == "rights":
            rights = self.repository.one(
                "SELECT * FROM rights_records WHERE id = ?", (subject_id,), "rights_records"
            )
            if not rights:
                return
            self.repository.update(
                "rights_records",
                subject_id,
                {"status": status, "review_notes": approval.get("reason")},
            )
            asset_status = "rights_approved" if status == "approved" else "rights_rejected"
            self.repository.execute(
                "UPDATE source_assets SET status = ? WHERE id = ?",
                (asset_status, rights["source_asset_id"]),
            )
        elif approval_type == "final_video":
            self.repository.update(
                "video_variants",
                subject_id,
                {"status": "approved" if status == "approved" else "rejected"},
            )
        elif approval_type == "provider_quote":
            self.repository.update(
                "provider_quotes", subject_id, {"status": status}
            )
        elif approval_type == "publish_final":
            self.repository.update(
                "publishing_jobs",
                subject_id,
                {"status": "ready" if status == "approved" else "rejected"},
            )
        elif approval_type == "initiative_plan":
            initiative = self.repository.one(
                "SELECT * FROM initiatives WHERE id = ?", (subject_id,), "initiatives"
            )
            if not initiative:
                return
            self.repository.update(
                "initiatives",
                subject_id,
                {"status": "active" if status == "approved" else "rejected"},
            )
            task_status = "queued" if status == "approved" else "cancelled"
            self.repository.execute(
                "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE initiative_id = ? AND status = 'proposed'",
                (task_status, subject_id),
            )

    # ------------------------------------------------------------------- people
    def list_businesses(self) -> list[dict[str, Any]]:
        rows = self.repository.many(
            "SELECT * FROM businesses ORDER BY created_at ASC", (), "businesses"
        )
        for row in rows:
            row["departments"] = self.repository.count(
                "departments", "business_id = ?", (row["id"],)
            )
            row["initiatives"] = self.repository.count(
                "initiatives", "business_id = ?", (row["id"],)
            )
        return rows

    def create_business(
        self, name: str, brand_rules: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("business name is required")
        business_id = str(uuid.uuid4())
        row = self.repository.insert(
            "businesses",
            {
                "id": business_id,
                "name": name.strip(),
                "status": "active",
                "brand_rules": brand_rules or {},
            },
        )
        self.repository.audit("founder", "business_created", business_id, {"name": name})
        return row

    def list_departments(self, include_workers: bool = True) -> list[dict[str, Any]]:
        departments = self.repository.many(
            "SELECT * FROM departments ORDER BY created_at ASC", (), "departments"
        )
        paused = set(self.repository.get_state("paused_departments", []))
        for department in departments:
            department["paused"] = department["id"] in paused
            department["worker_count"] = self.repository.count(
                "workers", "department_id = ?", (department["id"],)
            )
            department["active_worker_count"] = self.repository.count(
                "workers", "department_id = ? AND status = 'active'", (department["id"],)
            )
            department["open_tasks"] = self.repository.count(
                "tasks",
                "department = ? AND status IN ('queued','running','retry','waiting_approval')",
                (department["id"],),
            )
            department["completed_tasks"] = self.repository.count(
                "tasks", "department = ? AND status = 'completed'", (department["id"],)
            )
            if include_workers:
                department["workers"] = self.repository.many(
                    "SELECT * FROM workers WHERE department_id = ? ORDER BY created_at ASC",
                    (department["id"],),
                    "workers",
                )
                manager = next(
                    (
                        worker
                        for worker in department["workers"]
                        if worker["id"] == department.get("manager_worker_id")
                    ),
                    department["workers"][0] if department["workers"] else None,
                )
                department["manager"] = manager
        return departments

    def list_workers(self, department: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE w.department_id = ?" if department else ""
        params = (department,) if department else ()
        return self.repository.many(
            f"""
            SELECT w.*, d.name AS department_name,
                   t.title AS current_task_title, t.status AS current_task_status
            FROM workers w
            LEFT JOIN departments d ON d.id = w.department_id
            LEFT JOIN tasks t ON t.id = w.current_task_id
            {where}
            ORDER BY d.created_at ASC, w.created_at ASC
            """,
            params,
            "workers",
        )

    def update_worker(self, worker_id: str, status: str | None = None) -> dict[str, Any]:
        worker = self.repository.one(
            "SELECT * FROM workers WHERE id = ?", (worker_id,), "workers"
        )
        if not worker:
            raise NotFound("worker not found")
        if status and status not in {"active", "paused", "offline"}:
            raise ValueError("worker status must be active, paused, or offline")
        updated = self.repository.update(
            "workers",
            worker_id,
            {"status": status or worker["status"], "last_action": "Status updated by founder"},
        )
        self.repository.audit("founder", "worker_updated", worker_id, {"status": status})
        return updated

    def pause_department(self, department_id: str, paused: bool) -> dict[str, Any]:
        department = self.repository.one(
            "SELECT * FROM departments WHERE id = ?", (department_id,), "departments"
        )
        if not department:
            raise NotFound("department not found")
        paused_ids = set(self.repository.get_state("paused_departments", []))
        if paused:
            paused_ids.add(department_id)
        else:
            paused_ids.discard(department_id)
        self.repository.set_state("paused_departments", sorted(paused_ids))
        self.repository.execute(
            "UPDATE departments SET status = ? WHERE id = ?",
            ("paused" if paused else "active", department_id),
        )
        self.repository.execute(
            "UPDATE workers SET status = ? WHERE department_id = ? AND status != 'offline'",
            ("paused" if paused else "active", department_id),
        )
        self.repository.audit(
            "founder",
            "department_paused" if paused else "department_resumed",
            department_id,
        )
        return self._department(department_id)

    def _department(self, department_id: str) -> dict[str, Any]:
        for department in self.list_departments():
            if department["id"] == department_id:
                return department
        raise NotFound("department not found")

    # ------------------------------------------------------------------- rights
    def create_rights(
        self,
        *,
        source_asset_id: str,
        owner: str,
        license_type: str,
        commercial_use: bool,
        proof_uri: str | None = None,
        platforms: list[str] | None = None,
        attribution: str | None = None,
        takedown_contact: str | None = None,
        expires_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not owner.strip() or not license_type.strip():
            raise ValueError("owner and license_type are required")
        asset = self.repository.one(
            "SELECT * FROM source_assets WHERE id = ?", (source_asset_id,), "source_assets"
        )
        if not asset:
            raise NotFound("source asset not found")
        if expires_at:
            from app.policy import parse_timestamp

            if parse_timestamp(expires_at) is None:
                raise ValueError("expires_at must be an ISO date or timestamp")
        rights_id = str(uuid.uuid4())
        rights = self.repository.insert(
            "rights_records",
            {
                "id": rights_id,
                "source_asset_id": source_asset_id,
                "owner": owner.strip(),
                "license_type": license_type.strip(),
                "commercial_use": commercial_use,
                "proof_uri": proof_uri,
                "platforms": platforms or [],
                "attribution": attribution,
                "takedown_contact": takedown_contact,
                "expires_at": expires_at,
                "review_notes": notes,
                "status": "pending",
            },
        )
        self.repository.execute(
            "UPDATE source_assets SET status = 'rights_pending' WHERE id = ? "
            "AND status = 'pending_rights'",
            (source_asset_id,),
        )
        approval = self.create_approval(
            "rights",
            rights_id,
            subject_type="rights_record",
            requested_by="rights",
            reason=f"Rights review for {owner} ({license_type})",
        )
        self.repository.audit(
            "rights",
            "rights_record_created",
            rights_id,
            {"source_asset_id": source_asset_id, "owner": owner},
        )
        rights["approval"] = approval
        return rights

    def list_rights(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE r.status = ?" if status else ""
        params = (status,) if status else ()
        rows = self.repository.many(
            f"""
            SELECT r.*, a.filename, a.status AS asset_status, a.sha256
            FROM rights_records r
            LEFT JOIN source_assets a ON a.id = r.source_asset_id
            {where}
            ORDER BY r.created_at DESC
            """,
            params,
            "rights_records",
        )
        for row in rows:
            row["expired"] = is_expired(row.get("expires_at"))
        return rows

    def ingest_asset(
        self, path: str, rights_id: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        return self.media.register_asset(path, rights_id=rights_id, **kwargs)

    def list_assets(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE status = ?" if status else ""
        params = (status,) if status else ()
        rows = self.repository.many(
            f"SELECT * FROM source_assets {where} ORDER BY created_at DESC",
            params,
            "source_assets",
        )
        for row in rows:
            rights = self.repository.many(
                "SELECT * FROM rights_records WHERE source_asset_id = ? ORDER BY created_at DESC",
                (row["id"],),
                "rights_records",
            )
            row["rights"] = rights
            row["valid_rights"] = any(
                record["status"] == "approved"
                and record["commercial_use"]
                and not is_expired(record.get("expires_at"))
                for record in rights
            )
            row["candidates"] = self.repository.count(
                "highlight_candidates",
                "media_asset_id IN (SELECT id FROM media_assets WHERE source_asset_id = ?)",
                (row["id"],),
            )
            row["variants"] = self.repository.count(
                "video_variants",
                "candidate_id IN (SELECT id FROM highlight_candidates WHERE media_asset_id IN "
                "(SELECT id FROM media_assets WHERE source_asset_id = ?))",
                (row["id"],),
            )
        return rows

    # -------------------------------------------------------------------- tasks
    def create_task(
        self,
        title: str,
        department: str,
        worker: str | None = None,
        *,
        initiative_id: str | None = None,
        task_type: str = "general",
        priority: int = 3,
        input_ref: str | None = None,
        status: str = "queued",
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if not title.strip() or not department.strip():
            raise ValueError("title and department are required")
        worker_id = None
        worker_name = worker
        if worker:
            found = self.repository.one(
                "SELECT * FROM workers WHERE id = ? OR name = ?", (worker, worker), "workers"
            )
            if found:
                worker_id = found["id"]
                worker_name = found["name"]
        task_id = str(uuid.uuid4())
        row = self.repository.insert(
            "tasks",
            {
                "id": task_id,
                "initiative_id": initiative_id,
                "title": title.strip(),
                "department": department,
                "worker": worker_name,
                "worker_id": worker_id,
                "type": task_type,
                "status": status,
                "priority": priority,
                "input_ref": input_ref,
                "max_attempts": max_attempts,
            },
        )
        self.task_event(task_id, "created", {"title": title, "department": department}, "ceo")
        self.repository.audit(
            "ceo", "task_created", task_id, {"title": title, "department": department}
        )
        return row

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.repository.one("SELECT * FROM tasks WHERE id = ?", (task_id,), "tasks")
        if not row:
            raise NotFound("task not found")
        row["events"] = self.repository.many(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
            "task_events",
        )
        row["dependencies"] = [
            event["depends_on_task_id"]
            for event in self.repository.many(
                "SELECT * FROM task_dependencies WHERE task_id = ?", (task_id,), ""
            )
        ]
        return row

    def list_tasks(
        self,
        status: str | None = None,
        department: str | None = None,
        initiative_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        if department:
            clauses.append("t.department = ?")
            params.append(department)
        if initiative_id:
            clauses.append("t.initiative_id = ?")
            params.append(initiative_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self.repository.many(
            f"""
            SELECT t.*, w.avatar AS worker_avatar, w.name AS worker_name
            FROM tasks t
            LEFT JOIN workers w ON w.id = t.worker_id
            {where}
            ORDER BY t.priority ASC, t.created_at DESC
            """,
            params,
            "tasks",
        )

    def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        task = self.repository.one("SELECT * FROM tasks WHERE id = ?", (task_id,), "tasks")
        if not task:
            raise NotFound("task not found")
        allowed = {"title", "department", "worker", "worker_id", "priority", "status", "max_attempts"}
        clean = {key: value for key, value in updates.items() if key in allowed}
        if not clean:
            raise ValueError("no editable task fields supplied")
        updated = self.repository.update("tasks", task_id, clean)
        self.task_event(task_id, "updated", clean, "founder")
        self.repository.audit("founder", "task_updated", task_id, clean)
        return updated

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        task = self.repository.one("SELECT * FROM tasks WHERE id = ?", (task_id,), "tasks")
        if not task:
            raise NotFound("task not found")
        if task["status"] == "completed":
            raise Conflict("completed tasks cannot be cancelled")
        self.repository.update("tasks", task_id, {"status": "cancelled"})
        self.task_event(task_id, "cancelled", {}, "founder")
        self.repository.audit("founder", "task_cancelled", task_id)
        return self.get_task(task_id)

    def task_event(
        self, task_id: str, event_type: str, payload: dict[str, Any] | None = None, actor: str = "ceo"
    ) -> None:
        self.repository.insert(
            "task_events",
            {
                "task_id": task_id,
                "event_type": event_type,
                "payload": payload or {},
                "actor": actor,
            },
        )

    # ------------------------------------------------------------------ system
    def set_emergency_stop(self, active: bool, actor: str = "founder") -> dict[str, Any]:
        self.repository.set_state("emergency_stop", active)
        if active:
            self.repository.execute(
                "UPDATE cua_sessions SET status = 'stopped', closed_at = CURRENT_TIMESTAMP "
                "WHERE status = 'active'"
            )
        self.repository.audit(
            actor, "emergency_stop_engaged" if active else "emergency_stop_released", "company"
        )
        return self.system_status()

    def system_status(self) -> dict[str, Any]:
        return {
            "company_name": settings.company_name,
            "version": settings.app_version,
            "emergency_stop": self.repository.is_emergency_stopped(),
            "paused_departments": self.repository.get_state("paused_departments", []),
            "local_processing_enabled": settings.local_processing_enabled,
            "everygen_enabled": settings.everygen_enabled,
            "everygen_mock": settings.everygen_mock,
            "cua_enabled": settings.cua_enabled,
            "publishing_enabled": settings.publishing_enabled,
            "publishing_dry_run": settings.publishing_dry_run,
            "media_tools": media_tools(),
            "database": str(settings.database_path),
            "data_dir": str(settings.data_dir),
            "database_integrity": self.repository.integrity_check(),
            "counts": {
                "businesses": self.repository.count("businesses"),
                "departments": self.repository.count("departments"),
                "workers": self.repository.count("workers"),
                "tasks": self.repository.count("tasks"),
                "approvals_pending": self.repository.count("approvals", "status = 'pending'"),
                "assets": self.repository.count("source_assets"),
                "variants": self.repository.count("video_variants"),
                "posts": self.repository.count("platform_posts"),
            },
        }

    def backup(self) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = settings.backup_dir / f"factory-{stamp}.db"
        self.repository.backup(destination)
        self.repository.audit(
            "operations", "backup_created", str(destination), {"bytes": destination.stat().st_size}
        )
        return {
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "created_at": stamp,
            "integrity": self.repository.integrity_check(),
        }

    def list_backups(self) -> list[dict[str, Any]]:
        return [
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            for path in sorted(settings.backup_dir.glob("*.db"), reverse=True)
        ]

    # --------------------------------------------------------------- dashboard
    def _status_counts(self, table: str, column: str = "status") -> dict[str, int]:
        rows = self.repository.many(
            f"SELECT {column} AS status, COUNT(*) AS count FROM {table} GROUP BY {column}", (), ""
        )
        return {str(row["status"]): int(row["count"]) for row in rows}

    def activity(self, limit: int = 25, actor: str | None = None, action: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        return self.repository.many(
            f"SELECT * FROM audit_events {where} ORDER BY id DESC LIMIT ?",
            params,
            "audit_events",
        )

    def dashboard_summary(self) -> dict[str, Any]:
        pending = self.repository.count("approvals", "status = 'pending'")
        active_initiatives = self.repository.count(
            "initiatives", "status IN ('plan_pending','active')"
        )
        active_workers = self.repository.count("workers", "status = 'active'")
        costs = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events", (), "cost_events"
        )
        provider_costs = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events WHERE provider = 'everygen'",
            (),
            "cost_events",
        )
        posts = self.repository.count("platform_posts")
        views = self.repository.one(
            "SELECT COALESCE(SUM(views), 0) AS total FROM analytics_snapshots", (), ""
        )
        upcoming = self.repository.many(
            """
            SELECT j.*, v.title, v.style, v.qc_status
            FROM publishing_jobs j
            LEFT JOIN video_variants v ON v.id = j.video_variant_id
            WHERE j.status IN ('pending_approval','ready','scheduled')
            ORDER BY COALESCE(j.schedule_at, j.created_at) ASC
            LIMIT 8
            """,
            (),
            "publishing_jobs",
        )
        tasks = self._status_counts("tasks")
        assets = self._status_counts("source_assets")
        variants = self._status_counts("video_variants")
        approvals_by_type = {
            row["type"]: int(row["count"])
            for row in self.repository.many(
                "SELECT type, COUNT(*) AS count FROM approvals WHERE status = 'pending' GROUP BY type",
                (),
                "",
            )
        }
        qc_passed = (
            variants.get("qc_passed", 0)
            + variants.get("in_review", 0)
            + variants.get("approved", 0)
            + variants.get("published", 0)
        )
        qc_failed = variants.get("qc_failed", 0) + variants.get("render_failed", 0)
        qc_total = qc_passed + qc_failed
        rights = self.repository.many(
            "SELECT * FROM rights_records WHERE status = 'approved'", (), "rights_records"
        )
        expired = sum(1 for row in rights if is_expired(row.get("expires_at")))
        total_costs = float(costs["total"] if costs else 0)
        provider_spend = float(provider_costs["total"] if provider_costs else 0)
        provider_remaining = max(0.0, settings.everygen_budget_usd - provider_spend)
        alerts = self._alerts(
            pending, tasks, variants, expired, provider_remaining, active_initiatives
        )
        return {
            "company_name": settings.company_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "active_initiatives": active_initiatives,
            "pending_approvals": pending,
            "active_workers": active_workers,
            "workers_total": self.repository.count("workers"),
            "local_processing_enabled": settings.local_processing_enabled,
            "everygen_enabled": settings.everygen_enabled,
            "everygen_mock": settings.everygen_mock,
            "cua_enabled": settings.cua_enabled,
            "publishing_enabled": settings.publishing_enabled,
            "publishing_dry_run": settings.publishing_dry_run,
            "emergency_stop": self.repository.is_emergency_stopped(),
            "media_tools": media_tools(),
            "task_counts": tasks,
            "asset_counts": assets,
            "variant_counts": variants,
            "approvals_by_type": approvals_by_type,
            "quality": {
                "qc_pass_rate": round(qc_passed / qc_total * 100, 1) if qc_total else None,
                "qc_passed": qc_passed,
                "qc_failed": qc_failed,
                "rights_expired": expired,
            },
            "finance": {
                "total_cost_usd": round(total_costs, 2),
                "provider_spend_usd": round(provider_spend, 2),
                "provider_budget_usd": settings.everygen_budget_usd,
                "provider_remaining_usd": round(provider_remaining, 2),
                "cost_by_category": {
                    row["category"]: round(float(row["total"]), 2)
                    for row in self.repository.many(
                        "SELECT category, SUM(amount) AS total FROM cost_events GROUP BY category",
                        (),
                        "",
                    )
                },
            },
            "publishing": {
                "posts": posts,
                "views": int(views["total"] if views else 0),
                "upcoming": upcoming,
            },
            "alerts": alerts,
            "recent_activity": self.activity(10),
            "departments": self.list_departments(include_workers=False),
        }

    def _alerts(
        self,
        pending: int,
        tasks: dict[str, int],
        variants: dict[str, int],
        expired_rights: int,
        provider_remaining: float,
        active_initiatives: int,
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        if self.repository.is_emergency_stopped():
            alerts.append(
                {
                    "severity": "critical",
                    "title": "Emergency stop is active",
                    "detail": "All mutating operations are blocked until the founder resumes work.",
                }
            )
        if pending:
            alerts.append(
                {
                    "severity": "warning",
                    "title": f"{pending} approval{'s' if pending != 1 else ''} waiting",
                    "detail": "Rights, final video, spend, or publishing decisions need the founder.",
                }
            )
        dead_letter = tasks.get("dead_letter", 0)
        if dead_letter:
            alerts.append(
                {
                    "severity": "critical",
                    "title": f"{dead_letter} task{'s' if dead_letter != 1 else ''} in dead letter",
                    "detail": "Retry or cancel failed work from the Production Board.",
                }
            )
        if variants.get("render_failed", 0):
            alerts.append(
                {
                    "severity": "warning",
                    "title": "Render failures need attention",
                    "detail": "Open the production board to inspect the job error.",
                }
            )
        if expired_rights:
            alerts.append(
                {
                    "severity": "critical",
                    "title": f"{expired_rights} expired rights record{'s' if expired_rights != 1 else ''}",
                    "detail": "Expired rights cannot enter rendering or publishing.",
                }
            )
        if provider_remaining <= 0:
            alerts.append(
                {
                    "severity": "warning",
                    "title": "Everygen budget exhausted",
                    "detail": "New paid quotes are blocked until the founder raises the budget.",
                }
            )
        if not active_initiatives and not self.repository.count("tasks"):
            alerts.append(
                {
                    "severity": "info",
                    "title": "No active initiative",
                    "detail": "Send a strategic objective to the AI CEO to start the first production run.",
                }
            )
        return alerts

    def ceo_report(self) -> dict[str, Any]:
        completed = self.repository.count("tasks", "status = 'completed'")
        failed = self.repository.count("tasks", "status IN ('failed','dead_letter')")
        total = self.repository.count("tasks")
        pending = self.repository.count("approvals", "status = 'pending'")
        blockers = self.repository.many(
            "SELECT id, title, department, status, error, attempts FROM tasks "
            "WHERE status IN ('failed','dead_letter','waiting_approval') ORDER BY updated_at DESC LIMIT 10",
            (),
            "tasks",
        )
        return {
            "headline": "Founder Control Tower CEO report",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "throughput": {
                "tasks_total": total,
                "tasks_completed": completed,
                "tasks_failed": failed,
                "completion_rate": round(completed / total * 100, 1) if total else 0,
                "pending_approvals": pending,
            },
            "quality": self.dashboard_summary()["quality"],
            "finance": self.dashboard_summary()["finance"],
            "blockers": blockers,
            "recommendations": self._recommendations(pending, failed),
        }

    @staticmethod
    def _recommendations(pending: int, failed: int) -> list[str]:
        recommendations: list[str] = []
        if pending:
            recommendations.append("Clear the founder approval queue before starting new spend.")
        if failed:
            recommendations.append("Inspect dead-letter tasks and retry only with valid evidence.")
        if not recommendations:
            recommendations.append(
                "Send a strategic objective and run the next queued department tasks."
            )
        return recommendations


def ensure_high_risk_approval(
    service: FactoryService, approval_id: str | None, capability: str
) -> dict[str, Any]:
    if capability in HIGH_RISK_CAPABILITIES:
        return require_approval(service.repository, approval_id)
    if approval_id:
        return service.get_approval(approval_id)
    return {}
