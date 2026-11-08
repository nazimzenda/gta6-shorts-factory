from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.errors import NotFound, ValidationProblem
from app.services import FactoryService
from app.storage import Store


class AnalyticsService:
    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    # ----------------------------------------------------------------- snapshots
    def record_snapshot(
        self,
        platform_post_id: str,
        *,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        follows: int = 0,
        retention: float | None = None,
        watch_time: float | None = None,
        metadata: dict[str, Any] | None = None,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        post = self.repository.one(
            "SELECT * FROM platform_posts WHERE id = ?", (platform_post_id,), "platform_posts"
        )
        if not post:
            raise NotFound("platform post not found")
        values = {
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "follows": follows,
        }
        for name, value in values.items():
            if int(value) < 0:
                raise ValidationProblem(f"{name} cannot be negative")
        if retention is not None and not 0 <= float(retention) <= 100:
            raise ValidationProblem("retention must be a percentage between 0 and 100")
        snapshot = self.repository.insert(
            "analytics_snapshots",
            {
                "id": str(uuid.uuid4()),
                "platform_post_id": platform_post_id,
                "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
                "views": int(views),
                "likes": int(likes),
                "comments": int(comments),
                "shares": int(shares),
                "follows": int(follows),
                "retention": float(retention) if retention is not None else None,
                "watch_time": float(watch_time) if watch_time is not None else None,
                "metadata": metadata or {},
            },
        )
        self.repository.audit(
            "analytics",
            "analytics_snapshot_recorded",
            snapshot["id"],
            {"post_id": platform_post_id, "views": views},
        )
        return snapshot

    def list_snapshots(self, platform_post_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE s.platform_post_id = ?" if platform_post_id else ""
        params = (platform_post_id,) if platform_post_id else ()
        return self.repository.many(
            f"""
            SELECT s.*, p.platform, p.external_post_id, p.url
            FROM analytics_snapshots s
            LEFT JOIN platform_posts p ON p.id = s.platform_post_id
            {where}
            ORDER BY s.captured_at DESC
            """,
            params,
            "analytics_snapshots",
        )

    # --------------------------------------------------------------------- costs
    def record_cost(
        self,
        provider: str,
        category: str,
        amount: float,
        *,
        currency: str = "USD",
        task_id: str | None = None,
        job_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not provider.strip() or not category.strip():
            raise ValidationProblem("provider and category are required")
        if float(amount) < 0:
            raise ValidationProblem("amount cannot be negative")
        event = self.repository.insert(
            "cost_events",
            {
                "id": str(uuid.uuid4()),
                "provider": provider.strip(),
                "category": category.strip(),
                "amount": float(amount),
                "currency": currency,
                "task_id": task_id,
                "job_id": job_id,
                "note": note,
            },
        )
        self.repository.audit(
            "finance", "cost_recorded", event["id"], {"provider": provider, "amount": amount}
        )
        return event

    def list_costs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.repository.many(
            "SELECT * FROM cost_events ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
            "cost_events",
        )

    # ------------------------------------------------------------------- summary
    def summary(self) -> dict[str, Any]:
        task_counts = self._status_counts("tasks")
        asset_counts = self._status_counts("source_assets")
        variant_counts = self._status_counts("video_variants")
        approval_counts = self._status_counts("approvals")
        post_count = self.repository.count("platform_posts")
        simulated_posts = self.repository.count("platform_posts", "status = 'simulated'")
        latest_snapshots = self._latest_snapshots()
        total_views = sum(int(row.get("views") or 0) for row in latest_snapshots)
        total_likes = sum(int(row.get("likes") or 0) for row in latest_snapshots)
        total_comments = sum(int(row.get("comments") or 0) for row in latest_snapshots)
        total_shares = sum(int(row.get("shares") or 0) for row in latest_snapshots)
        total_follows = sum(int(row.get("follows") or 0) for row in latest_snapshots)
        retention_rows = [
            float(row["retention"]) for row in latest_snapshots if row.get("retention") is not None
        ]
        avg_retention = (
            round(sum(retention_rows) / len(retention_rows), 2) if retention_rows else None
        )
        total_cost = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events", (), "cost_events"
        )
        provider_cost = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events WHERE provider = 'everygen'",
            (),
            "cost_events",
        )
        cost_by_category = {
            row["category"]: round(float(row["total"]), 2)
            for row in self.repository.many(
                "SELECT category, SUM(amount) AS total FROM cost_events GROUP BY category "
                "ORDER BY total DESC",
                (),
                "",
            )
        }
        cost_by_provider = {
            row["provider"]: round(float(row["total"]), 2)
            for row in self.repository.many(
                "SELECT provider, SUM(amount) AS total FROM cost_events GROUP BY provider "
                "ORDER BY total DESC",
                (),
                "",
            )
        }
        avg_decision = self.repository.one(
            "SELECT AVG((julianday(decided_at) - julianday(created_at)) * 24 * 60) AS minutes "
            "FROM approvals WHERE decided_at IS NOT NULL",
            (),
            "",
        )
        qc_passed = (
            variant_counts.get("qc_passed", 0)
            + variant_counts.get("in_review", 0)
            + variant_counts.get("approved", 0)
            + variant_counts.get("published", 0)
        )
        qc_failed = variant_counts.get("qc_failed", 0) + variant_counts.get("render_failed", 0)
        qc_total = qc_passed + qc_failed
        posts = self.repository.many(
            """
            SELECT p.*, j.video_variant_id, j.platform, v.title, v.style
            FROM platform_posts p
            LEFT JOIN publishing_jobs j ON j.id = p.publishing_job_id
            LEFT JOIN video_variants v ON v.id = j.video_variant_id
            ORDER BY p.created_at DESC
            """,
            (),
            "platform_posts",
        )
        post_map = {row["id"]: row for row in posts}
        for snapshot in latest_snapshots:
            post = post_map.get(snapshot["platform_post_id"])
            if post:
                post["latest"] = snapshot
        top_posts = sorted(
            post_map.values(),
            key=lambda row: int((row.get("latest") or {}).get("views") or 0),
            reverse=True,
        )[:5]

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "production": {
                "tasks": task_counts,
                "tasks_completed": task_counts.get("completed", 0),
                "assets": asset_counts,
                "variants": variant_counts,
                "approved_variants": variant_counts.get("approved", 0)
                + variant_counts.get("published", 0),
                "rights_approved_assets": self.repository.count(
                    "rights_records", "status = 'approved'"
                ),
                "rights_pending_assets": self.repository.count(
                    "rights_records", "status = 'pending'"
                ),
            },
            "quality": {
                "qc_pass_rate": round(qc_passed / qc_total * 100, 1) if qc_total else None,
                "qc_passed": qc_passed,
                "qc_failed": qc_failed,
                "render_failures": variant_counts.get("render_failed", 0),
            },
            "approvals": {
                "counts": approval_counts,
                "pending": approval_counts.get("pending", 0),
                "approved": approval_counts.get("approved", 0),
                "rejected": approval_counts.get("rejected", 0),
                "average_decision_minutes": round(float(avg_decision["minutes"]), 1)
                if avg_decision and avg_decision.get("minutes") is not None
                else None,
                "by_type": {
                    row["type"]: {
                        "pending": int(row["pending"]),
                        "approved": int(row["approved"]),
                        "rejected": int(row["rejected"]),
                    }
                    for row in self.repository.many(
                        "SELECT type, "
                        "SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending, "
                        "SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved, "
                        "SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected "
                        "FROM approvals GROUP BY type",
                        (),
                        "",
                    )
                },
            },
            "publishing": {
                "posts": post_count,
                "simulated_posts": simulated_posts,
                "views": total_views,
                "likes": total_likes,
                "comments": total_comments,
                "shares": total_shares,
                "follows": total_follows,
                "average_retention": avg_retention,
                "follows_per_thousand_views": round(total_follows / total_views * 1000, 2)
                if total_views
                else None,
                "top_posts": top_posts,
            },
            "finance": {
                "total_cost_usd": round(float(total_cost["total"] if total_cost else 0), 2),
                "provider_spend_usd": round(
                    float(provider_cost["total"] if provider_cost else 0), 2
                ),
                "provider_budget_usd": settings.everygen_budget_usd,
                "provider_remaining_usd": round(
                    max(
                        0.0,
                        settings.everygen_budget_usd
                        - float(provider_cost["total"] if provider_cost else 0),
                    ),
                    2,
                ),
                "by_category": cost_by_category,
                "by_provider": cost_by_provider,
            },
            "daily": self._daily_series(14),
            "experiments": self._style_performance(),
        }

    def _latest_snapshots(self) -> list[dict[str, Any]]:
        rows = self.repository.many(
            "SELECT * FROM analytics_snapshots ORDER BY platform_post_id, captured_at DESC, rowid DESC",
            (),
            "analytics_snapshots",
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest.setdefault(row["platform_post_id"], row)
        return list(latest.values())

    def _status_counts(self, table: str) -> dict[str, int]:
        return {
            str(row["status"]): int(row["count"])
            for row in self.repository.many(
                f"SELECT status, COUNT(*) AS count FROM {table} GROUP BY status", (), ""
            )
        }

    def _daily_series(self, days: int) -> list[dict[str, Any]]:
        today = date.today()
        start = today - timedelta(days=days - 1)
        costs = {
            row["day"]: float(row["total"])
            for row in self.repository.many(
                "SELECT date(created_at) AS day, SUM(amount) AS total FROM cost_events "
                "WHERE date(created_at) >= ? GROUP BY day",
                (start.isoformat(),),
                "",
            )
        }
        posts = {
            row["day"]: int(row["count"])
            for row in self.repository.many(
                "SELECT date(created_at) AS day, COUNT(*) AS count FROM platform_posts "
                "WHERE date(created_at) >= ? GROUP BY day",
                (start.isoformat(),),
                "",
            )
        }
        tasks = {
            row["day"]: int(row["count"])
            for row in self.repository.many(
                "SELECT date(completed_at) AS day, COUNT(*) AS count FROM tasks "
                "WHERE completed_at IS NOT NULL AND date(completed_at) >= ? GROUP BY day",
                (start.isoformat(),),
                "",
            )
        }
        series = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            series.append(
                {
                    "date": day,
                    "cost_usd": round(costs.get(day, 0.0), 2),
                    "posts": posts.get(day, 0),
                    "tasks_completed": tasks.get(day, 0),
                }
            )
        return series

    def _style_performance(self) -> list[dict[str, Any]]:
        rows = self.repository.many(
            """
            SELECT v.style,
                   COUNT(DISTINCT p.id) AS posts,
                   COALESCE(SUM(s.views), 0) AS views,
                   COALESCE(AVG(s.retention), 0) AS retention
            FROM video_variants v
            JOIN publishing_jobs j ON j.video_variant_id = v.id
            JOIN platform_posts p ON p.publishing_job_id = j.id
            LEFT JOIN (
                SELECT s1.* FROM analytics_snapshots s1
                JOIN (
                    SELECT platform_post_id, MAX(captured_at) AS latest
                    FROM analytics_snapshots GROUP BY platform_post_id
                ) newest ON newest.platform_post_id = s1.platform_post_id
                AND newest.latest = s1.captured_at
            ) s ON s.platform_post_id = p.id
            GROUP BY v.style
            ORDER BY views DESC
            """,
            (),
            "",
        )
        return [
            {
                "style": row["style"],
                "posts": int(row["posts"]),
                "views": int(row["views"]),
                "average_retention": round(float(row["retention"]), 2),
            }
            for row in rows
        ]

    # -------------------------------------------------------------------- reports
    def daily_report(self) -> dict[str, Any]:
        today = date.today().isoformat()
        tasks_completed = self.repository.one(
            "SELECT COUNT(*) AS count FROM tasks WHERE date(completed_at) = ?", (today,), ""
        )
        approvals = self.repository.many(
            "SELECT * FROM approvals WHERE date(decided_at) = ?", (today,), "approvals"
        )
        posts = self.repository.one(
            "SELECT COUNT(*) AS count FROM platform_posts WHERE date(created_at) = ?", (today,), ""
        )
        spend = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events WHERE date(created_at) = ?",
            (today,),
            "cost_events",
        )
        return {
            "date": today,
            "tasks_completed": int(tasks_completed["count"] if tasks_completed else 0),
            "approvals_decided": len(approvals),
            "approvals_approved": sum(1 for row in approvals if row["status"] == "approved"),
            "approvals_rejected": sum(1 for row in approvals if row["status"] == "rejected"),
            "posts_created": int(posts["count"] if posts else 0),
            "spend_usd": round(float(spend["total"] if spend else 0), 2),
            "blockers": self.service.ceo_report()["blockers"],
            "recommendations": self.service.ceo_report()["recommendations"],
        }

    def weekly_report(self) -> dict[str, Any]:
        week_start = (date.today() - timedelta(days=6)).isoformat()
        tasks_completed = self.repository.one(
            "SELECT COUNT(*) AS count FROM tasks WHERE completed_at IS NOT NULL "
            "AND date(completed_at) >= ?",
            (week_start,),
            "",
        )
        approvals = self.repository.many(
            "SELECT * FROM approvals WHERE decided_at IS NOT NULL AND date(decided_at) >= ?",
            (week_start,),
            "approvals",
        )
        posts = self.repository.one(
            "SELECT COUNT(*) AS count FROM platform_posts WHERE date(created_at) >= ?",
            (week_start,),
            "",
        )
        spend = self.repository.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM cost_events WHERE date(created_at) >= ?",
            (week_start,),
            "cost_events",
        )
        return {
            "week_start": week_start,
            "week_end": date.today().isoformat(),
            "tasks_completed": int(tasks_completed["count"] if tasks_completed else 0),
            "approvals_decided": len(approvals),
            "posts_created": int(posts["count"] if posts else 0),
            "spend_usd": round(float(spend["total"] if spend else 0), 2),
            "cost_per_post_usd": round(
                float(spend["total"] if spend else 0) / int(posts["count"] or 1), 2
            )
            if posts and int(posts["count"])
            else 0.0,
            "summary": self.summary(),
        }

    def export_report(self) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = settings.export_dir / f"founder-report-{stamp}.json"
        payload = {
            "company": settings.company_name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "daily": self.daily_report(),
            "weekly": self.weekly_report(),
            "audit_events": self.repository.many(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT 500", (), "audit_events"
            ),
        }
        destination.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self.repository.audit("analytics", "report_exported", str(destination))
        return {
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "generated_at": stamp,
        }
