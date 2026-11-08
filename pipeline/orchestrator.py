"""Pipeline orchestrator: discover → Everygen → download → publish → repeat."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pipeline.clipper import ClipperStage
from pipeline.config import PipelineSettings
from pipeline.cua_sandbox import CuaSandbox
from pipeline.db import PipelineDB
from pipeline.errors import AuthError, LimitError, PipelineError, PlanRequired
from pipeline.everygen import EverygenStage
from pipeline.guest_runner import GuestRunner
from pipeline.publish import PublishStage
from pipeline.yt_search import discover

LOGGER = logging.getLogger("pipeline.orchestrator")


@dataclass
class CycleResult:
    run_id: str
    status: str
    stats: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    auth_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stats": self.stats,
            "error": self.error,
            "auth_required": self.auth_required,
        }


class Pipeline:
    def __init__(
        self,
        settings: PipelineSettings,
        *,
        db: PipelineDB | None = None,
        sandbox: CuaSandbox | None = None,
        guest: GuestRunner | None = None,
    ) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.db = db or PipelineDB(settings.db_path)
        self.sandbox = sandbox or CuaSandbox(settings)
        self.guest = guest or GuestRunner(settings, self.sandbox)
        self.everygen = EverygenStage(settings, self.db, self.guest)
        self.clipper = ClipperStage(settings, self.db)
        self.publisher = PublishStage(settings, self.db, self.guest)

    # ------------------------------------------------------------- guard rails
    def emergency_stopped(self) -> bool:
        if not self.settings.respect_factory_emergency_stop:
            return False
        path = Path(self.settings.factory_db)
        if not path.is_file():
            return False
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                rows = connection.execute(
                    "SELECT key, value FROM system_state "
                    "WHERE key IN ('emergency_stop', 'cua_emergency_stop')"
                ).fetchall()
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            return False
        for _, value in rows:
            try:
                stopped = bool(json.loads(value))
            except (TypeError, ValueError):
                stopped = str(value).strip().lower() in {"1", "true", "yes", "on"}
            if stopped:
                return True
        return False

    def _assert_emergency_clear(self) -> None:
        if self.emergency_stopped():
            raise PipelineError(
                "the Founder Control Tower emergency stop is active; resume it "
                "in the dashboard before running the pipeline"
            )

    # ---------------------------------------------------------------- prepare
    def prepare(self) -> dict[str, Any]:
        if not self.settings.cua_enabled:
            raise PipelineError(
                "CUA is disabled. Set CUA_ENABLED=true in .env after the owner "
                "has signed in to the VM."
            )
        self._assert_emergency_clear()
        sandbox = self.sandbox.ensure_running()
        if not sandbox.get("ok"):
            raise PipelineError(f"Cua sandbox unavailable: {sandbox.get('error')}")
        self.guest.ensure()
        self.guest.deploy()
        return {
            "ok": True,
            "sandbox": self.sandbox.status(),
            "guest_scripts": [
                path.name for path in self.guest.local_guest_dir.glob("*.py")
            ],
        }

    def prepare_logins(self) -> dict[str, Any]:
        result = self.prepare()
        job = self.guest.open_logins()
        view = self.sandbox.view_url()
        return {
            **result,
            "open_logins": job.to_dict(),
            "view_url": view,
            "instructions": (
                "Open the view_url in a browser on this machine and sign in to "
                "YouTube Studio, TikTok Studio and everygen.ai. The agent never "
                "asks for your passwords and never stores them."
            ),
        }

    # --------------------------------------------------------------- accounts
    def accounts(self) -> dict[str, Any]:
        self.prepare()
        job = self.guest.check_accounts()
        payload = job.payload or {}
        accounts = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(accounts, dict):
            accounts = {}
        required: list[str] = []
        if (self.settings.mode or "generate").lower() != "clip":
            required.append("everygen")
        if self.settings.platform_enabled("youtube"):
            required.append("youtube")
        if self.settings.platform_enabled("tiktok"):
            required.append("tiktok")
        missing = [
            name
            for name in required
            if not bool((accounts.get(name) or {}).get("logged_in"))
        ]
        return {
            "ok": not missing and job.ok,
            "accounts": accounts,
            "missing": missing,
            "view_url": self.sandbox.view_url(),
            "job": job.to_dict(),
        }

    def _assert_accounts(self) -> dict[str, Any]:
        result = self.accounts()
        if not result["ok"]:
            missing = ", ".join(result.get("missing") or []) or "unknown"
            raise AuthError(
                f"sign in required in the CUA VM for: {missing}. Open "
                f"{result.get('view_url') or 'the CUA viewer'} and sign in, then "
                "run `python -m pipeline.run accounts`."
            )
        return result

    # -------------------------------------------------------------- discovery
    @staticmethod
    def _title_key(title: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()

    def discover(
        self,
        *,
        limit: int | None = None,
        queries: Iterable[str] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        limit = int(limit or self.settings.links_per_cycle)
        queries = list(queries or self.settings.queries)
        found = discover(
            queries,
            per_query=self.settings.results_per_query,
            min_views=self.settings.min_views,
            timeout=self.settings.search_timeout,
        )
        created = 0
        duplicates = 0
        selected: list[dict[str, Any]] = []
        existing_titles = {
            self._title_key(str(row.get("title") or ""))
            for row in self.db.links(limit=10_000)
        }
        for link in found:
            if created >= limit:
                break
            title_key = self._title_key(link.title)
            if title_key and title_key in existing_titles:
                duplicates += 1
                continue
            link_id, is_new = self.db.add_link(link.as_dict())
            if is_new:
                created += 1
                if title_key:
                    existing_titles.add(title_key)
                selected.append({"id": link_id, **link.as_dict()})
            else:
                duplicates += 1
        stats = {
            "queries": len(queries),
            "found": len(found),
            "new": created,
            "duplicates": duplicates,
            "selected": selected,
        }
        self.db.log_event(
            "discover.stage",
            f"found={len(found)} new={created} duplicates={duplicates}",
            run_id=run_id,
            payload={k: v for k, v in stats.items() if k != "selected"},
        )
        return stats

    # --------------------------------------------------------------- generation
    def generate(
        self,
        *,
        limit: int | None = None,
        variants: int | None = None,
        link_id: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self.everygen.generate(
                limit=limit, variants=variants, link_id=link_id, run_id=run_id
            )
        except (AuthError, PlanRequired):
            self._release_generating_links()
            raise

    def _release_generating_links(self) -> None:
        for link in self.db.links(status="generating", limit=1000):
            self.db.update_link(int(link["id"]), status="new", error="released after failure")

    def clip(
        self,
        *,
        url: str | None = None,
        link_id: int | None = None,
        count: int | None = None,
        start: float | None = None,
        end: float | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if url:
            return self.clipper.clip_url(
                url,
                count=count,
                start=start,
                end=end,
                link_id=link_id,
                run_id=run_id,
            )
        if link_id is not None:
            link = self.db.get_link(link_id)
            if not link:
                raise PipelineError(f"link {link_id} not found")
            return self.clipper.clip_link(
                link, count=int(count or self.settings.clip_count),
                start=start, end=end, run_id=run_id,
            )
        raise PipelineError("a YouTube URL or --link-id is required")

    # ---------------------------------------------------------------- publish
    def publish(
        self,
        *,
        limit: int | None = None,
        platforms: Iterable[str] | None = None,
        live: bool | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return self.publisher.publish(
            limit=limit, platforms=platforms, live=live, run_id=run_id
        )

    # ------------------------------------------------------------------ cycle
    def cycle(
        self,
        *,
        live: bool | None = None,
        links: int | None = None,
        variants: int | None = None,
        max_shorts: int | None = None,
        skip_auth_check: bool = False,
        run_id: str | None = None,
    ) -> CycleResult:
        live = self.settings.live if live is None else bool(live)
        mode = (self.settings.mode or "generate").lower()
        variants = int(variants or self.settings.variants_per_link)
        max_shorts = max(1, int(max_shorts or self.settings.max_shorts_per_cycle))
        # Never ask for more outputs than the cycle budget allows.
        per_link = int(self.settings.clip_count) if mode == "clip" else variants
        per_link = max(1, min(per_link, max_shorts))
        if mode != "clip":
            variants = per_link
        links = int(links or self.settings.links_per_cycle)
        max_links = max(1, max_shorts // max(1, per_link))
        links = max(1, min(links, max_links))
        run_id = run_id or self.db.create_run("cycle")
        stats: dict[str, Any] = {
            "mode": mode,
            "live": live,
            "links_budget": links,
            "per_link": per_link,
            "variants_per_link": variants,
            "max_shorts": max_shorts,
        }
        try:
            self._assert_emergency_clear()
            self.prepare()
            if self.settings.require_auth_check and not skip_auth_check:
                stats["accounts"] = self._assert_accounts()
            stats["discover"] = self.discover(limit=links, run_id=run_id)
            if mode == "clip":
                stats["clip"] = self.clipper.generate(
                    limit=links, count=per_link, run_id=run_id
                )
            else:
                stats["generate"] = self.generate(
                    limit=links, variants=variants, run_id=run_id
                )
            stats["publish"] = self.publish(
                limit=max_shorts, live=live, run_id=run_id
            )
            self.db.finish_run(run_id, "completed", stats)
            return CycleResult(run_id=run_id, status="completed", stats=stats)
        except AuthError as error:
            self.db.finish_run(run_id, "auth_required", stats, str(error))
            self.db.log_event("cycle.auth", str(error), run_id=run_id)
            return CycleResult(
                run_id=run_id,
                status="auth_required",
                stats=stats,
                error=str(error),
                auth_required=True,
            )
        except LimitError as error:
            self.db.finish_run(run_id, "limited", stats, str(error))
            return CycleResult(
                run_id=run_id, status="limited", stats=stats, error=str(error)
            )
        except Exception as error:  # noqa: BLE001 - run state must be persisted
            LOGGER.exception("pipeline cycle failed")
            self.db.finish_run(run_id, "failed", stats, str(error))
            self.db.log_event("cycle.failed", str(error), run_id=run_id)
            return CycleResult(
                run_id=run_id, status="failed", stats=stats, error=str(error)
            )

    def worker(
        self,
        *,
        interval: int = 3600,
        live: bool | None = None,
        max_cycles: int | None = None,
    ) -> list[CycleResult]:
        results: list[CycleResult] = []
        cycles = 0
        while True:
            result = self.cycle(live=live)
            results.append(result)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if result.status == "auth_required":
                LOGGER.warning("worker paused: owner sign-in required")
            time.sleep(max(30, int(interval)))
        return results

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "db": self.db.stats(),
            "sandbox": self.sandbox.status(),
            "settings": {
                "mode": self.settings.mode,
                "cua_enabled": self.settings.cua_enabled,
                "platforms": self.settings.platforms,
                "live_default": self.settings.live,
                "queries": self.settings.queries,
                "variants_per_link": self.settings.variants_per_link,
                "clip_count": self.settings.clip_count,
                "clip_min_seconds": self.settings.clip_min_seconds,
                "clip_max_seconds": self.settings.clip_max_seconds,
                "clip_quality": self.settings.clip_quality,
                "clip_layout": self.settings.clip_layout,
                "clip_show_title": self.settings.clip_show_title,
                "clip_show_captions": self.settings.clip_show_captions,
                "clip_transcribe_fallback": self.settings.clip_transcribe_fallback,
                "whisper_model": self.settings.whisper_model,
                "rights_ack": self.settings.rights_ack,
                "max_shorts_per_cycle": self.settings.max_shorts_per_cycle,
                "everygen_format": self.settings.everygen_format,
                "everygen_budget_credits": self.settings.everygen_budget_credits,
                "guest_profile": self.settings.guest_profile,
            },
        }

    def reset_stuck(self) -> dict[str, Any]:
        """Release rows left mid-flight by a crash; never deletes artifacts."""
        released_links = 0
        for link in self.db.links(status="generating", limit=10000):
            self.db.update_link(
                int(link["id"]), status="new", error="reset after interrupted run"
            )
            released_links += 1
        released_generations = 0
        for generation in self.db.generations(status="generating", limit=10000):
            self.db.update_generation(
                int(generation["id"]), status="failed", error="interrupted run"
            )
            released_generations += 1
        released_posts = 0
        for post in self.db.posts(status="publishing", limit=10000):
            self.db.update_post(
                int(post["id"]), status="failed", error="interrupted run"
            )
            released_posts += 1
        return {
            "links": released_links,
            "generations": released_generations,
            "posts": released_posts,
        }
