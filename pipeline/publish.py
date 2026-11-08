"""Publish downloaded shorts to YouTube and TikTok through the Cua VM.

The platform accounts are the owner's already signed-in Firefox sessions in
the VM.  This stage never logs in, never asks for a password and never touches
a platform API key.  ``live=False`` stops on the review screen (dry run);
``live=True`` clicks the final Publish/Post button.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable

from pipeline.config import PipelineSettings
from pipeline.db import PipelineDB
from pipeline.errors import AuthError, PublishError
from pipeline.guest_runner import GuestRunner, JobResult

LOGGER = logging.getLogger("pipeline.publish")


def _clean_title(value: str, limit: int = 90) -> str:
    title = re.sub(r"\s+", " ", (value or "").strip())
    title = re.sub(r"#shorts\b", "", title, flags=re.I).strip()
    return title[:limit].strip(" -|")


class PublishStage:
    def __init__(
        self, settings: PipelineSettings, db: PipelineDB, guest: GuestRunner
    ) -> None:
        self.settings = settings
        self.db = db
        self.guest = guest

    # ------------------------------------------------------------------ copy
    def _remote_video(self, generation: dict[str, Any]) -> str:
        host_path = Path(str(generation.get("host_path") or ""))
        if not host_path.is_file():
            raise PublishError(f"generated video is missing: {host_path}")
        remote_dir = f"{self.settings.guest_media_dir}/gta_pipeline"
        remote_path = f"{remote_dir}/{generation['id']}-{host_path.name}"
        self.guest.sandbox.copy_to_guest(host_path, remote_path)
        return remote_path

    # --------------------------------------------------------------- metadata
    def metadata(
        self, generation: dict[str, Any], link: dict[str, Any]
    ) -> dict[str, str]:
        base = _clean_title(
            str(generation.get("title") or link.get("title") or "GTA 6 Short"),
            80,
        )
        if not base:
            base = "GTA 6 Open World Short"
        source_title = _clean_title(str(link.get("title") or ""), 100)
        source_url = str(link.get("url") or "")
        is_clip = str(generation.get("direction") or "").startswith("clip ")
        disclosure = (
            "Highlight clip from a public YouTube source, shared with attribution."
            if is_clip
            else "AI-generated GTA 6 style gameplay short."
        )
        inspiration = (
            f"Source: {source_title} ({source_url})."
            if source_title
            else ""
        )
        youtube_title = f"{base} #Shorts"
        if len(youtube_title) > 100:
            youtube_title = youtube_title[:100].rstrip()
        # The proven guest uploaders cap YouTube descriptions at 500 chars and
        # TikTok captions at 200; keep the host-side metadata inside the same
        # envelope so nothing is silently truncated at the last step.
        provenance = (
            "Only reuse footage you own or have permission to publish."
            if is_clip
            else "Original AI-generated footage; no source footage was reused."
        )
        youtube_description = " ".join(
            part
            for part in (
                disclosure,
                inspiration,
                provenance,
                self.settings.youtube_hashtags,
            )
            if part
        )[:480]
        tiktok_caption = " ".join(
            part
            for part in (
                base[:140],
                self.settings.tiktok_hashtags,
            )
            if part
        )[:200]
        return {
            "youtube_title": youtube_title,
            "youtube_description": youtube_description,
            "tiktok_caption": tiktok_caption,
            "base": base,
        }

    # ----------------------------------------------------------------- result
    @staticmethod
    def _error_text(result: JobResult) -> str:
        payload = result.payload or {}
        return str(payload.get("error") or payload.get("message") or "").strip()

    def _auth_error(self, result: JobResult, platform: str) -> None:
        error = self._error_text(result)
        if result.exit_code == 2 or "not_logged_in" in error.lower():
            raise AuthError(
                f"{platform} is not signed in inside the CUA VM. Sign in in the "
                "VM, then run `python -m pipeline.run accounts`."
            )

    def _record_post(
        self,
        post: dict[str, Any],
        result: JobResult,
        *,
        platform: str,
        live: bool,
    ) -> str:
        attempts = int(post.get("attempts") or 0) + 1
        self._auth_error(result, platform)
        payload = result.payload or {}
        if result.ok:
            if live:
                self.db.update_post(
                    post["id"],
                    status="published",
                    live=1,
                    attempts=attempts,
                    remote_hint=str(
                        payload.get("url")
                        or payload.get("remote_id")
                        or payload.get("video_id")
                        or ""
                    ),
                    error=None,
                )
                return "published"
            self.db.update_post(
                post["id"],
                status="dry_run",
                live=0,
                attempts=attempts,
                remote_hint=str(payload.get("note") or "dry-run"),
                error=None,
            )
            return "dry_run"
        message = self._error_text(result) or f"guest exit {result.exit_code}"
        terminal = attempts >= max(1, self.settings.retry_limit)
        self.db.update_post(
            post["id"],
            status="failed" if not terminal else "skipped",
            live=0,
            attempts=attempts,
            error=message[:1000],
        )
        return "failed"

    # ------------------------------------------------------------------ stage
    def publish_generation(
        self,
        generation: dict[str, Any],
        *,
        platforms: Iterable[str],
        live: bool,
    ) -> dict[str, Any]:
        generation_id = int(generation["id"])
        link = self.db.get_link(int(generation["link_id"])) or {}
        metadata = self.metadata(generation, link)
        remote_video = self._remote_video(generation)
        posts = {post["platform"]: post for post in self.db.posts_for_generation(generation_id)}
        stats = {"generation": generation_id, "published": 0, "dry_run": 0, "failed": 0, "deferred": 0}
        for platform in platforms:
            post = posts.get(platform)
            if post is None:
                self.db.enqueue_posts(generation_id, [platform])
                post = next(
                    (
                        item
                        for item in self.db.posts_for_generation(generation_id)
                        if item["platform"] == platform
                    ),
                    None,
                )
            if post is None:
                stats["failed"] += 1
                continue
            if post["status"] == "skipped":
                continue
            if post["status"] == "published":
                stats["published"] += 1
                continue
            if post["status"] == "dry_run" and not live:
                stats["dry_run"] += 1
                continue
            daily_limit = (
                self.settings.daily_limit_youtube
                if platform == "youtube"
                else self.settings.daily_limit_tiktok
            )
            if live and daily_limit > 0:
                already = self.db.daily_published_count(platform)
                if already >= daily_limit:
                    message = f"daily {platform} publish limit reached ({already}/{daily_limit})"
                    self.db.update_post(post["id"], status="deferred", error=message)
                    self.db.log_event("publish.limit", message, generation_id)
                    stats["deferred"] += 1
                    continue
            self.db.update_post(
                post["id"],
                status="publishing",
                live=1 if live else 0,
                attempts=int(post.get("attempts") or 0) + 1,
            )
            try:
                if platform == "youtube":
                    result = self.guest.publish_youtube(
                        video=remote_video,
                        title=metadata["youtube_title"],
                        description=metadata["youtube_description"],
                        live=live,
                    )
                elif platform == "tiktok":
                    result = self.guest.publish_tiktok(
                        video=remote_video,
                        caption=metadata["tiktok_caption"],
                        live=live,
                    )
                else:
                    continue
                outcome = self._record_post(
                    post, result, platform=platform, live=live
                )
                if outcome == "published":
                    stats["published"] += 1
                elif outcome == "dry_run":
                    stats["dry_run"] += 1
                else:
                    stats["failed"] += 1
            except AuthError:
                self.db.update_post(
                    post["id"],
                    status="failed",
                    live=0,
                    attempts=int(post.get("attempts") or 0) + 1,
                    error="NOT_LOGGED_IN",
                )
                raise
            except Exception as error:  # noqa: BLE001 - keep the rest of the batch alive
                self.db.update_post(
                    post["id"],
                    status="failed",
                    live=0,
                    attempts=int(post.get("attempts") or 0) + 1,
                    error=str(error)[:1000],
                )
                stats["failed"] += 1
                LOGGER.warning("%s publish failed for %s: %s", platform, generation_id, error)

        posts = self.db.posts_for_generation(generation_id)
        statuses = {post["platform"]: post["status"] for post in posts}
        active = [statuses.get(platform) for platform in platforms]
        if active and all(status == "published" for status in active):
            self.db.update_generation(generation_id, status="published", error=None)
            self._maybe_finish_link(int(generation["link_id"]))
        elif any(status == "published" for status in active):
            self.db.update_generation(generation_id, status="partially_published")
        else:
            self.db.update_generation(generation_id, status="ready")
        self.db.log_event(
            "publish.stage",
            f"generation {generation_id}: {stats}",
            generation_id,
            payload=stats,
        )
        return stats

    def _maybe_finish_link(self, link_id: int) -> None:
        generations = [
            row
            for row in self.db.generations(limit=1000)
            if int(row["link_id"]) == link_id
        ]
        active = [row for row in generations if row["status"] not in {"failed", "skipped", "qc_failed"}]
        if active and all(row["status"] == "published" for row in active):
            self.db.update_link(link_id, status="done", error=None)

    def publish(
        self,
        *,
        limit: int | None = None,
        platforms: Iterable[str] | None = None,
        live: bool | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        platforms = [
            platform
            for platform in (platforms or self.settings.platforms)
            if self.settings.platform_enabled(platform)
        ]
        live = self.settings.live if live is None else bool(live)
        limit = int(limit or self.settings.max_shorts_per_cycle)
        generations = self.db.publishable_generations(platforms, limit=limit)
        totals = {
            "generations": 0,
            "published": 0,
            "dry_run": 0,
            "failed": 0,
            "deferred": 0,
        }
        for generation in generations:
            totals["generations"] += 1
            try:
                result = self.publish_generation(
                    generation, platforms=platforms, live=live
                )
                for key in ("published", "dry_run", "failed", "deferred"):
                    totals[key] += int(result.get(key) or 0)
            except AuthError:
                raise
            except Exception as error:  # noqa: BLE001
                totals["failed"] += 1
                LOGGER.warning(
                    "Publish generation %s failed: %s", generation.get("id"), error
                )
        if totals["generations"]:
            self.db.log_event(
                "publish.batch",
                f"published={totals['published']} dry_run={totals['dry_run']} "
                f"failed={totals['failed']}",
                run_id=run_id,
                payload=totals,
            )
        return totals
