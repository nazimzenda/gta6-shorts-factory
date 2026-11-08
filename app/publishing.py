from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.errors import ApprovalRequired, Conflict, NotFound, PolicyError, ValidationProblem
from app.policy import require_approval, require_running
from app.services import FactoryService
from app.storage import Store

SUPPORTED_PLATFORMS = {"youtube", "tiktok"}


class PublishingService:
    """Dry-run-first publishing with a hard final-video approval lock."""

    def __init__(self, repository: Store, service: FactoryService) -> None:
        self.repository = repository
        self.service = service

    # ----------------------------------------------------------------- accounts
    def list_accounts(self) -> list[dict[str, Any]]:
        return self.repository.many(
            "SELECT * FROM publishing_accounts ORDER BY created_at ASC",
            (),
            "publishing_accounts",
        )

    def create_account(
        self, platform: str, display_name: str, credential_ref: str | None = None
    ) -> dict[str, Any]:
        platform = platform.lower().strip()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValidationProblem("platform must be youtube or tiktok")
        if not display_name.strip():
            raise ValidationProblem("display_name is required")
        account = self.repository.insert(
            "publishing_accounts",
            {
                "id": str(uuid.uuid4()),
                "platform": platform,
                "display_name": display_name.strip(),
                "credential_ref": credential_ref,
                "status": "active",
            },
        )
        self.repository.audit(
            "publishing",
            "publishing_account_created",
            account["id"],
            {"platform": platform, "display_name": display_name},
        )
        return account

    def update_account(self, account_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "paused", "revoked"}:
            raise ValidationProblem("account status must be active, paused, or revoked")
        account = self.repository.one(
            "SELECT * FROM publishing_accounts WHERE id = ?",
            (account_id,),
            "publishing_accounts",
        )
        if not account:
            raise NotFound("publishing account not found")
        self.repository.update("publishing_accounts", account_id, {"status": status})
        self.repository.audit("founder", "publishing_account_updated", account_id, {"status": status})
        return self.repository.one(
            "SELECT * FROM publishing_accounts WHERE id = ?", (account_id,), "publishing_accounts"
        ) or {}

    # --------------------------------------------------------------------- jobs
    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = self.repository.many(
            "SELECT * FROM publishing_jobs ORDER BY created_at DESC", (), "publishing_jobs"
        )
        for job in jobs:
            job["variant"] = self.repository.one(
                "SELECT id, title, style, qc_status, status, render_uri FROM video_variants WHERE id = ?",
                (job["video_variant_id"],),
                "video_variants",
            )
            job["approval"] = self.repository.one(
                "SELECT * FROM approvals WHERE id = ?", (job.get("approval_id"),), "approvals"
            )
            job["post"] = self.repository.one(
                "SELECT * FROM platform_posts WHERE publishing_job_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (job["id"],),
                "platform_posts",
            )
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.one(
            "SELECT * FROM publishing_jobs WHERE id = ?", (job_id,), "publishing_jobs"
        )
        if not job:
            raise NotFound("publishing job not found")
        variant = self.repository.one(
            "SELECT * FROM video_variants WHERE id = ?",
            (job["video_variant_id"],),
            "video_variants",
        )
        job["variant"] = variant
        job["approval"] = self.repository.one(
            "SELECT * FROM approvals WHERE id = ?", (job.get("approval_id"),), "approvals"
        )
        job["final_video_approval"] = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'final_video' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (job["video_variant_id"],),
            "approvals",
        )
        job["post"] = self.repository.one(
            "SELECT * FROM platform_posts WHERE publishing_job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
            "platform_posts",
        )
        return job

    def create_job(
        self,
        video_variant_id: str,
        platform: str,
        account_id: str | None = None,
        schedule_at: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        platform = platform.lower().strip()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValidationProblem("platform must be youtube or tiktok")
        if schedule_at:
            from app.policy import parse_timestamp

            if parse_timestamp(schedule_at) is None:
                raise ValidationProblem("schedule_at must be an ISO timestamp")
        variant = self.repository.one(
            "SELECT * FROM video_variants WHERE id = ?",
            (video_variant_id,),
            "video_variants",
        )
        if not variant:
            raise NotFound("video variant not found")
        if variant["qc_status"] != "passed":
            raise PolicyError("variant must pass QC before a publishing job can be created")
        final_approval = self.repository.one(
            "SELECT * FROM approvals WHERE type = 'final_video' AND subject_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (video_variant_id,),
            "approvals",
        )
        if not final_approval or final_approval["status"] != "approved":
            raise ApprovalRequired("final video must be approved before scheduling a publish")
        account = None
        if account_id:
            account = self.repository.one(
                "SELECT * FROM publishing_accounts WHERE id = ?",
                (account_id,),
                "publishing_accounts",
            )
            if not account:
                raise NotFound("publishing account not found")
            if account["platform"] != platform:
                raise ValidationProblem("account platform does not match the publishing job")
            if account["status"] != "active":
                raise PolicyError("publishing account is not active")

        idempotency_key = hashlib.sha256(
            f"{video_variant_id}:{platform}:{schedule_at or 'immediate'}:{account_id or 'default'}".encode()
        ).hexdigest()
        existing = self.repository.one(
            "SELECT * FROM publishing_jobs WHERE idempotency_key = ?",
            (idempotency_key,),
            "publishing_jobs",
        )
        if existing:
            existing["duplicate"] = True
            return existing

        job_id = str(uuid.uuid4())
        job = self.repository.insert(
            "publishing_jobs",
            {
                "id": job_id,
                "video_variant_id": video_variant_id,
                "platform": platform,
                "account_id": account_id,
                "schedule_at": schedule_at,
                "status": "pending_approval",
                "payload": payload or {},
                "idempotency_key": idempotency_key,
            },
        )
        approval = self.service.create_approval(
            "publish_final",
            job_id,
            subject_type="publishing_job",
            requested_by="publishing",
            reason=f"Approve {platform} publish for {variant['title']}",
        )
        self.repository.update("publishing_jobs", job_id, {"approval_id": approval["id"]})
        self.repository.audit(
            "publishing",
            "publishing_job_created",
            job_id,
            {"platform": platform, "variant_id": video_variant_id, "approval_id": approval["id"]},
            approval["id"],
        )
        job = self.get_job(job_id)
        job["approval"] = approval
        job["duplicate"] = False
        return job

    def publish(self, job_id: str) -> dict[str, Any]:
        require_running(self.repository)
        job = self.get_job(job_id)
        if job["status"] == "published" and job.get("post"):
            return job
        require_approval(
            self.repository,
            job.get("approval_id"),
            expected_type="publish_final",
            subject_id=job_id,
        )
        variant_approval = job.get("final_video_approval")
        if not variant_approval or variant_approval["status"] != "approved":
            raise ApprovalRequired("final video approval is required before publishing")
        variant = job.get("variant") or {}
        if variant.get("qc_status") != "passed":
            raise PolicyError("variant QC must pass before publishing")
        if not settings.publishing_dry_run and not settings.publishing_enabled:
            raise PolicyError(
                "publishing is disabled; enable PUBLISHING_ENABLED only after platform review"
            )
        if not settings.publishing_dry_run:
            raise PolicyError(
                "live platform adapters are not configured. Add an approved OAuth adapter "
                "before disabling PUBLISHING_DRY_RUN."
            )
        post_id = str(uuid.uuid4())
        external_id = f"dryrun-{job['platform']}-{post_id[:12]}"
        post = self.repository.insert(
            "platform_posts",
            {
                "id": post_id,
                "publishing_job_id": job_id,
                "platform": job["platform"],
                "external_post_id": external_id,
                "url": f"https://example.invalid/{job['platform']}/{external_id}",
                "status": "simulated",
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.repository.update(
            "publishing_jobs", job_id, {"status": "published", "error": None}
        )
        self.repository.execute(
            "UPDATE video_variants SET status = 'published', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (job["video_variant_id"],),
        )
        self.repository.insert(
            "cost_events",
            {
                "id": str(uuid.uuid4()),
                "provider": "platform",
                "category": "publishing",
                "amount": 0.0,
                "currency": "USD",
                "job_id": job_id,
                "note": "dry-run publish; no platform API was contacted",
            },
        )
        self.repository.audit(
            "publishing",
            "publish_dry_run_completed",
            job_id,
            {"platform": job["platform"], "external_post_id": external_id},
            job.get("approval_id"),
        )
        result = self.get_job(job_id)
        result["post"] = post
        return result

    def reconcile(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        post = job.get("post")
        if not post:
            raise Conflict("publishing job has no platform post to reconcile")
        if post["status"] == "simulated":
            self.repository.audit(
                "publishing", "post_reconciled", post["id"], {"status": "simulated"}
            )
            return {
                "job": job,
                "post": post,
                "reconciled": True,
                "note": "dry-run post remains simulated; no platform API was contacted",
            }
        raise PolicyError("live post reconciliation requires a configured platform adapter")

    def list_posts(self) -> list[dict[str, Any]]:
        posts = self.repository.many(
            "SELECT * FROM platform_posts ORDER BY created_at DESC", (), "platform_posts"
        )
        for post in posts:
            post["snapshots"] = self.repository.count(
                "analytics_snapshots", "platform_post_id = ?", (post["id"],)
            )
            post["job"] = self.repository.one(
                "SELECT id, platform, video_variant_id, status FROM publishing_jobs WHERE id = ?",
                (post["publishing_job_id"],),
                "publishing_jobs",
            )
        return posts
