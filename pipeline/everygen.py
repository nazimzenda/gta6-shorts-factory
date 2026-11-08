"""Host-side Everygen generation stage.

Everygen is driven in the Cua VM through its logged-in Shorts Studio web UI.
No Everygen API key, MCP token or developer API is used.  The guest script
selects the ``GTA 6`` format, submits a direction based on the discovered
YouTube link, waits for the clip to finish and downloads it; this module pulls
the resulting file back to the host, probes it and queues it for publishing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pipeline.config import PipelineSettings
from pipeline.db import PipelineDB
from pipeline.errors import AuthError, LimitError, PipelineError, PlanRequired
from pipeline.guest_runner import GuestRunner, JobResult
from pipeline.media import is_vertical, looks_like_video, probe_video, safe_stem

LOGGER = logging.getLogger("pipeline.everygen")

# Variants are deliberately different so a source link produces a range of
# shorts rather than near-duplicates.  The source URL/title is still included
# in every prompt for provenance and topic grounding.
VARIANT_TITLES = (
    "Neon Drift",
    "Beachfront Chaos",
    "Swamp Crossing",
    "Tank Run",
)

VARIANT_DIRECTIONS = (
    (
        "A stolen neon-orange muscle car idles at a rain-soaked Vice City "
        "intersection at night. The driver floors it into a cinematic drift as "
        "police lights flood the frame; a flamingos-and-palm-trees open-world "
        "satire tone, one absurd near-miss, strong engine sound."
    ),
    (
        "A sun-drenched coastal boulevard in a GTA 6 style open world. A "
        "monster truck launches over a sports car while beachgoers scatter and "
        "a police helicopter banks overhead. Fast, playful, over-the-top chaos "
        "with a clean 1-second hook."
    ),
    (
        "A quiet scenic drive along a swamp road turns absurd when an alligator "
        "crosses at the worst possible moment. The driver swerves, a delivery "
        "scooter spins past, and the camera catches the whole escalating mess in "
        "one cinematic take."
    ),
    (
        "A motorcycle courier weaves through downtown traffic as a stolen tank "
        "rolls the wrong way down the opposite lane. Neon signs, sparks, "
        "sirens, and one perfectly timed near-miss; photoreal GTA 6 style "
        "open-world gameplay with a punchline ending."
    ),
)


class EverygenStage:
    def __init__(
        self, settings: PipelineSettings, db: PipelineDB, guest: GuestRunner
    ) -> None:
        self.settings = settings
        self.db = db
        self.guest = guest

    # ------------------------------------------------------------------ prompt
    @staticmethod
    def variant_title(variant: int) -> str:
        return f"{VARIANT_TITLES[variant % len(VARIANT_TITLES)]} | GTA 6"

    def build_direction(self, link: dict[str, Any], variant: int) -> str:
        title = str(link.get("title") or "GTA 6 reference").strip()
        url = str(link.get("url") or "").strip()
        direction = VARIANT_DIRECTIONS[variant % len(VARIANT_DIRECTIONS)]
        prefix = self.settings.everygen_prompt_prefix
        prompt = (
            f"{prefix}\n"
            f"Reference YouTube link: {url}\n"
            f"Source title: {title}\n"
            f"Direction: {direction}\n"
            f"Output: one {self.settings.everygen_duration} 9:16 "
            f"{self.settings.everygen_quality} vertical clip with sound. "
            "Original AI-generated footage only; no source footage, logos, "
            "characters or music; no on-screen text."
        )
        return prompt[:2000]

    # ------------------------------------------------------------------ result
    @staticmethod
    def _error_text(payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        return str(payload.get("error") or payload.get("message") or "").strip()

    def _raise_for_error(self, result: JobResult) -> None:
        payload = result.payload or {}
        error = self._error_text(payload)
        lowered = error.lower()
        if result.exit_code == 2 or "not_logged_in" in lowered:
            raise AuthError(
                "Everygen is not signed in inside the CUA VM. Open the VM, "
                "sign in to everygen.ai, then run `python -m pipeline.run accounts`."
            )
        if "plan_required" in lowered or "pick a plan" in lowered:
            raise PlanRequired(
                "Everygen has no active plan or credits. Open everygen.ai in the "
                "CUA VM, choose a plan / top up credits, then run the generation "
                "again. The source link and prompt direction are already saved."
            )
        if any(
            token in lowered
            for token in (
                "insufficient credit",
                "not enough credit",
                "no credits",
                "credit limit",
                "limit reached",
                "daily limit",
                "quota",
            )
        ):
            raise LimitError(error or "Everygen credit/limit reached")
        if result.timed_out:
            raise PipelineError(error or f"Everygen timed out after {result.duration_s:.0f}s")
        if result.exit_code != 0 and not result.ok:
            raise PipelineError(error or f"Everygen guest job failed ({result.exit_code})")

    @staticmethod
    def _video_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
        videos = payload.get("videos")
        if isinstance(videos, list):
            return [item for item in videos if isinstance(item, dict) and item.get("path")]
        path = payload.get("path") or payload.get("video_path")
        if path:
            return [{"path": path}]
        return []

    def _copy_to_host(
        self, generation_id: int, entry: dict[str, Any], link: dict[str, Any]
    ) -> dict[str, Any]:
        guest_path = str(entry.get("path") or "").strip()
        if not guest_path:
            raise PipelineError("Everygen returned no downloadable path")
        suffix = Path(guest_path).suffix or ".mp4"
        if suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv"}:
            suffix = ".mp4"
        generation = self.db.get_generation(generation_id) or {}
        title_stem = safe_stem(
            str(
                generation.get("title")
                or entry.get("title")
                or link.get("title")
                or "gta6"
            ),
            "gta6",
        )
        host_path = (
            self.settings.videos_dir
            / f"gen{generation_id:05d}-{title_stem}{suffix}"
        )
        host_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = host_path.with_suffix(host_path.suffix + ".part")
        try:
            self.guest.sandbox.copy_from_guest(guest_path, temp_path)
        except Exception as error:  # noqa: BLE001 - surfaced as a pipeline error
            raise PipelineError(
                f"could not copy generated video from guest ({guest_path}): {error}"
            ) from error
        if not temp_path.exists():
            raise PipelineError(f"guest copy did not create {temp_path}")
        size = temp_path.stat().st_size
        if size < self.settings.video_min_bytes:
            temp_path.unlink(missing_ok=True)
            raise PipelineError(
                f"generated file is too small ({size} bytes < "
                f"{self.settings.video_min_bytes})"
            )
        os.replace(temp_path, host_path)
        probe = probe_video(host_path)
        if probe.get("ok"):
            try:
                self.db.update_generation(
                    generation_id,
                    host_path=str(host_path),
                    guest_path=guest_path,
                    duration_seconds=probe.get("duration_seconds"),
                    width=probe.get("width"),
                    height=probe.get("height"),
                    credits=float(entry.get("credits") or 0),
                )
            except (TypeError, ValueError):
                pass
        else:
            self.db.update_generation(
                generation_id,
                host_path=str(host_path),
                guest_path=guest_path,
                credits=float(entry.get("credits") or 0),
            )
        return {"path": str(host_path), "probe": probe, "bytes": size}

    def _accept_video(self, generation_id: int, copied: dict[str, Any]) -> bool:
        probe = copied.get("probe") or {}
        path = str(copied.get("path") or "")
        if not looks_like_video(path):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error=(
                    "downloaded file is not an MP4/WebM/MOV container; "
                    "it is probably an HTML error page"
                ),
            )
            return False
        if probe.get("ok") and not is_vertical(probe):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error=(
                    "generated clip is not vertical: "
                    f"{probe.get('width')}x{probe.get('height')}"
                ),
            )
            return False
        if not probe.get("ok") and "ffprobe not installed" not in str(
            probe.get("error") or ""
        ):
            self.db.update_generation(
                generation_id,
                status="qc_failed",
                error=f"ffprobe rejected the file: {probe.get('error')}",
            )
            return False
        self.db.update_generation(generation_id, status="ready", error=None)
        self.db.enqueue_posts(generation_id, self.settings.platforms)
        return True

    # ------------------------------------------------------------------- stage
    def generate_link(
        self, link: dict[str, Any], variants: int, run_id: str | None = None
    ) -> dict[str, Any]:
        link_id = int(link["id"])
        stats = {"generations": 0, "ready": 0, "failed": 0, "skipped": 0, "deferred": 0}
        pending = self.db.pending_variants(
            link_id, variants, retry_limit=self.settings.retry_limit
        )
        if not pending:
            existing = self.db.generations_for_link(link_id)
            statuses = {str(row["status"]) for row in existing}
            if statuses & {"ready", "published", "partially_published"}:
                self.db.update_link(link_id, status="generated", error=None)
            elif "deferred" in statuses:
                self.db.update_link(link_id, status="new", error="deferred")
            elif statuses & {"failed", "qc_failed"}:
                self.db.update_link(link_id, status="failed", error="no usable variants")
            else:
                self.db.update_link(link_id, status="skipped", error="no pending variants")
            return stats
        for variant in pending:
            remaining_budget = 0.0
            if self.settings.everygen_budget_credits > 0:
                remaining_budget = max(
                    0.0,
                    self.settings.everygen_budget_credits
                    - self.db.credits_spent(),
                )
                if remaining_budget < self.settings.everygen_estimated_credits:
                    message = (
                        "Everygen daily credit budget reached "
                        f"({self.db.credits_spent():.0f}/"
                        f"{self.settings.everygen_budget_credits:.0f})"
                    )
                    self.db.update_link(link_id, status="new", error=message)
                    self.db.log_event("everygen.limit", message, link_id, run_id)
                    stats["deferred"] += 1
                    break

            direction = self.build_direction(link, variant)
            generation_id = self.db.create_generation(
                link_id, variant, direction=direction, status="generating"
            )
            current = self.db.get_generation(generation_id) or {}
            self.db.update_generation(
                generation_id,
                attempts=int(current.get("attempts") or 0) + 1,
                title=self.variant_title(variant),
            )
            LOGGER.info(
                "Everygen: link=%s variant=%s generation=%s",
                link_id,
                variant,
                generation_id,
            )
            try:
                result = self.guest.generate_video(
                    link=str(link.get("url") or ""),
                    direction=direction,
                    title=str(link.get("title") or ""),
                    variant=variant,
                    budget_credits=remaining_budget if remaining_budget else None,
                )
                self._raise_for_error(result)
                entries = self._video_entries(result.payload or {})
                if not entries:
                    raise PipelineError(
                        "Everygen finished without a downloadable video path"
                    )
                for index, entry in enumerate(entries):
                    target_id = generation_id
                    if index:
                        extra_variant = variant + 100 + index
                        target_id = self.db.create_generation(
                            link_id,
                            extra_variant,
                            direction=direction,
                            status="generating",
                        )
                        self.db.update_generation(
                            target_id,
                            title=self.variant_title(extra_variant),
                        )
                    stats["generations"] += 1
                    try:
                        copied = self._copy_to_host(target_id, entry, link)
                        accepted = self._accept_video(target_id, copied)
                    except PipelineError as error:
                        self.db.update_generation(
                            target_id, status="failed", error=str(error)[:1000]
                        )
                        stats["failed"] += 1
                        LOGGER.warning("Everygen video rejected: %s", error)
                        continue
                    if accepted:
                        stats["ready"] += 1
                    else:
                        stats["failed"] += 1
            except AuthError:
                # An auth failure is not a generation failure: keep the variant
                # retryable with a clean attempt counter so the next run resumes
                # as soon as the owner signs in.
                self.db.update_generation(
                    generation_id,
                    status="pending",
                    attempts=0,
                    error="NOT_LOGGED_IN",
                )
                self.db.update_link(link_id, status="new", error="NOT_LOGGED_IN")
                raise
            except PlanRequired as error:
                self.db.update_generation(
                    generation_id, status="deferred", error=str(error)[:1000]
                )
                self.db.update_link(link_id, status="new", error=str(error)[:1000])
                self.db.log_event("everygen.plan_required", str(error), link_id, run_id)
                stats["deferred"] += 1
                raise
            except LimitError as error:
                self.db.update_generation(
                    generation_id, status="deferred", error=str(error)[:1000]
                )
                self.db.update_link(link_id, status="new", error=str(error)[:1000])
                self.db.log_event("everygen.limit", str(error), link_id, run_id)
                stats["deferred"] += 1
                break
            except PipelineError as error:
                self.db.update_generation(
                    generation_id, status="failed", error=str(error)[:1000]
                )
                stats["failed"] += 1
                LOGGER.warning("Everygen variant %s failed: %s", variant, error)
                continue

        if stats["ready"]:
            self.db.update_link(link_id, status="generated", error=None)
        elif stats["deferred"]:
            self.db.update_link(link_id, status="new", error="deferred by provider limit")
        elif stats["skipped"]:
            self.db.update_link(link_id, status="skipped", error="limit reached")
        elif stats["failed"]:
            self.db.update_link(link_id, status="failed", error="all variants failed")
        self.db.log_event(
            "everygen.stage",
            f"link {link_id}: {stats}",
            link_id,
            run_id,
            payload=stats,
        )
        return stats

    def generate(
        self,
        *,
        limit: int | None = None,
        variants: int | None = None,
        link_id: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        variants = int(variants or self.settings.variants_per_link)
        if link_id is not None:
            link = self.db.get_link(link_id)
            if not link:
                raise PipelineError(f"link {link_id} not found")
            links = [link]
        else:
            limit = int(limit or self.settings.links_per_cycle)
            links = self.db.claim_links(limit)
        totals = {
            "links": 0,
            "generations": 0,
            "ready": 0,
            "failed": 0,
            "skipped": 0,
            "deferred": 0,
        }
        for link in links:
            totals["links"] += 1
            result = self.generate_link(link, variants=variants, run_id=run_id)
            for key in ("generations", "ready", "failed", "skipped", "deferred"):
                totals[key] += int(result.get(key) or 0)
        return totals
