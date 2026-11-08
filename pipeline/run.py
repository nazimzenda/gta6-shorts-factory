"""Command line entry point for the CUA pipeline.

Examples
--------
    python -m pipeline.run prepare          # start/recover the CUA VM
    python -m pipeline.run open-logins      # open YouTube/TikTok/Everygen tabs
    python -m pipeline.run accounts         # verify the three sessions
    python -m pipeline.run discover         # scrape GTA 6 YouTube links
    python -m pipeline.run cycle --live     # one full discover→generate→publish run
    python -m pipeline.run worker --live    # repeat the cycle forever
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from pipeline.config import PipelineSettings, load_settings
from pipeline.errors import AuthError, PipelineError
from pipeline.orchestrator import Pipeline


def _settings(args: argparse.Namespace) -> PipelineSettings:
    settings = load_settings()
    if getattr(args, "dry_run", False):
        settings.live = False
    elif getattr(args, "live", False):
        settings.live = True
    if getattr(args, "platform", None):
        settings.platforms = list(args.platform)
    if getattr(args, "mode", None):
        settings.mode = str(args.mode).lower()
    if getattr(args, "rights_ack", False):
        settings.rights_ack = True
    return settings


def _dump(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str, sort_keys=False))


def _pipeline(args: argparse.Namespace) -> Pipeline:
    settings = _settings(args)
    settings.ensure_dirs()
    return Pipeline(settings)


def _print_cycle(result: Any) -> int:
    _dump(result.to_dict())
    if result.status == "completed":
        return 0
    if result.status == "auth_required":
        return 2
    return 1


def cmd_prepare(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.prepare())
    return 0


def cmd_open_logins(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.prepare_logins())
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.accounts()
    _dump(result)
    return 0 if result.get("ok") else 2


def cmd_sandbox(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    action = args.action
    if action == "status":
        result = pipeline.sandbox.status()
    elif action == "start":
        result = pipeline.sandbox.start()
    elif action == "suspend":
        result = pipeline.sandbox.suspend()
    elif action == "resume":
        result = pipeline.sandbox.resume()
    elif action == "recover":
        result = pipeline.sandbox.recover()
    elif action == "view":
        result = {"view_url": pipeline.sandbox.view_url()}
    elif action == "screenshot":
        result = pipeline.sandbox.screenshot()
    else:  # pragma: no cover - argparse choices prevent this
        raise SystemExit(f"unknown sandbox action: {action}")
    _dump(result)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    queries = args.query or None
    result = pipeline.discover(limit=args.limit, queries=queries)
    _dump(result)
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.generate(
        limit=args.limit, variants=args.variants, link_id=args.link_id
    )
    _dump(result)
    return 0


def cmd_clip(args: argparse.Namespace) -> int:
    if not args.url and args.link_id is None:
        _dump({"ok": False, "error": "provide --url or --link-id"})
        return 1
    pipeline = _pipeline(args)
    result = pipeline.clip(
        url=args.url,
        link_id=args.link_id,
        count=args.count,
        start=args.start,
        end=args.end,
    )
    _dump(result)
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.publish(
        limit=args.limit,
        platforms=args.platform or None,
        live=pipeline.settings.live,
    )
    _dump(result)
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    result = pipeline.cycle(
        live=pipeline.settings.live,
        links=args.links,
        variants=args.variants,
        max_shorts=args.max_shorts,
        skip_auth_check=args.skip_auth_check,
    )
    return _print_cycle(result)


def cmd_worker(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    try:
        results = pipeline.worker(
            interval=args.interval,
            live=pipeline.settings.live,
            max_cycles=args.max_cycles,
        )
    except KeyboardInterrupt:
        print("worker interrupted", file=sys.stderr)
        return 130
    _dump([result.to_dict() for result in results])
    return 0 if all(result.status == "completed" for result in results) else 1


def cmd_status(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.status())
    return 0


def cmd_links(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.db.links(status=args.status, limit=args.limit))
    return 0


def cmd_generations(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.db.generations(status=args.status, limit=args.limit))
    return 0


def cmd_posts(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.db.posts(status=args.status, limit=args.limit))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.db.runs(limit=args.limit))
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.db.events(limit=args.limit, run_id=args.run_id))
    return 0


def cmd_skip_link(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    link = pipeline.db.get_link(args.id)
    if not link:
        _dump({"ok": False, "error": f"link {args.id} not found"})
        return 1
    pipeline.db.update_link(
        args.id, status="skipped", error=args.reason or "skipped by operator"
    )
    _dump({"ok": True, "id": args.id, "status": "skipped"})
    return 0


def cmd_requeue_link(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    link = pipeline.db.get_link(args.id)
    if not link:
        _dump({"ok": False, "error": f"link {args.id} not found"})
        return 1
    pipeline.db.update_link(args.id, status="new", error=None)
    _dump({"ok": True, "id": args.id, "status": "new"})
    return 0


def cmd_reset_stuck(args: argparse.Namespace) -> int:
    pipeline = _pipeline(args)
    _dump(pipeline.reset_stuck())
    return 0


def _add_publish_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--live",
        action="store_true",
        help="actually click Publish/Post (overrides PIPELINE_LIVE)",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="stop on the platform review screen",
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=("youtube", "tiktok"),
        help="limit publishing to one platform (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description=(
            "GTA 6 Shorts Factory — CUA pipeline. No platform API keys: all "
            "account actions use the owner's signed-in Cua VM sessions."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="debug logging on the host"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="start/recover the CUA VM and deploy guest scripts")
    sub.add_parser("open-logins", help="open YouTube/TikTok/Everygen tabs in the VM")
    sub.add_parser("accounts", help="check the three signed-in browser sessions")

    sandbox = sub.add_parser("sandbox", help="Cua sandbox lifecycle")
    sandbox.add_argument(
        "action",
        choices=("status", "start", "suspend", "resume", "recover", "view", "screenshot"),
    )

    discover_parser = sub.add_parser("discover", help="scrape GTA 6 YouTube links")
    discover_parser.add_argument("--limit", type=int, default=None)
    discover_parser.add_argument(
        "--query", action="append", default=None, help="override a search query"
    )

    generate_parser = sub.add_parser("generate", help="generate shorts in Everygen")
    generate_parser.add_argument("--limit", type=int, default=None)
    generate_parser.add_argument("--variants", type=int, default=None)
    generate_parser.add_argument("--link-id", type=int, default=None)

    clip_parser = sub.add_parser(
        "clip", help="free local YouTube highlight clipper (requires rights ack)"
    )
    clip_parser.add_argument("--url", default=None, help="public YouTube link")
    clip_parser.add_argument("--link-id", type=int, default=None)
    clip_parser.add_argument("--count", type=int, default=None)
    clip_parser.add_argument("--start", type=float, default=None)
    clip_parser.add_argument("--end", type=float, default=None)
    clip_parser.add_argument(
        "--rights-ack",
        action="store_true",
        help="confirm you own the source or have permission to reuse it",
    )

    publish_parser = sub.add_parser("publish", help="publish ready shorts")
    publish_parser.add_argument("--limit", type=int, default=None)
    _add_publish_flags(publish_parser)

    cycle_parser = sub.add_parser("cycle", help="one full pipeline cycle")
    cycle_parser.add_argument("--links", type=int, default=None)
    cycle_parser.add_argument("--variants", type=int, default=None)
    cycle_parser.add_argument("--max-shorts", type=int, default=None)
    cycle_parser.add_argument("--skip-auth-check", action="store_true")
    cycle_parser.add_argument(
        "--mode", choices=("generate", "clip"), default=None,
        help="generate = Everygen AI; clip = local YouTube highlights",
    )
    cycle_parser.add_argument(
        "--rights-ack",
        action="store_true",
        help="confirm you own the source or have permission to reuse it",
    )
    _add_publish_flags(cycle_parser)

    worker_parser = sub.add_parser("worker", help="repeat the cycle forever")
    worker_parser.add_argument("--interval", type=int, default=3600)
    worker_parser.add_argument("--max-cycles", type=int, default=None)
    worker_parser.add_argument(
        "--mode", choices=("generate", "clip"), default=None,
        help="generate = Everygen AI; clip = local YouTube highlights",
    )
    worker_parser.add_argument(
        "--rights-ack",
        action="store_true",
        help="confirm you own the source or have permission to reuse it",
    )
    _add_publish_flags(worker_parser)

    sub.add_parser("status", help="pipeline, sandbox and database status")

    links_parser = sub.add_parser("links", help="list discovered links")
    links_parser.add_argument("--status", default=None)
    links_parser.add_argument("--limit", type=int, default=50)

    generations_parser = sub.add_parser("generations", help="list generations")
    generations_parser.add_argument("--status", default=None)
    generations_parser.add_argument("--limit", type=int, default=50)

    posts_parser = sub.add_parser("posts", help="list publish attempts")
    posts_parser.add_argument("--status", default=None)
    posts_parser.add_argument("--limit", type=int, default=50)

    runs_parser = sub.add_parser("runs", help="list pipeline runs")
    runs_parser.add_argument("--limit", type=int, default=20)

    events_parser = sub.add_parser("events", help="list pipeline events")
    events_parser.add_argument("--limit", type=int, default=100)
    events_parser.add_argument("--run-id", default=None)

    skip_parser = sub.add_parser("skip-link", help="exclude a discovered link")
    skip_parser.add_argument("--id", type=int, required=True)
    skip_parser.add_argument("--reason", default="skipped by operator")

    requeue_parser = sub.add_parser("requeue-link", help="put a link back in the queue")
    requeue_parser.add_argument("--id", type=int, required=True)

    sub.add_parser("reset-stuck", help="release rows left mid-flight by a crash")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    handlers = {
        "prepare": cmd_prepare,
        "open-logins": cmd_open_logins,
        "accounts": cmd_accounts,
        "sandbox": cmd_sandbox,
        "discover": cmd_discover,
        "generate": cmd_generate,
        "clip": cmd_clip,
        "publish": cmd_publish,
        "cycle": cmd_cycle,
        "worker": cmd_worker,
        "status": cmd_status,
        "links": cmd_links,
        "generations": cmd_generations,
        "posts": cmd_posts,
        "runs": cmd_runs,
        "events": cmd_events,
        "skip-link": cmd_skip_link,
        "requeue-link": cmd_requeue_link,
        "reset-stuck": cmd_reset_stuck,
    }
    handler = handlers.get(args.command)
    if handler is None:  # pragma: no cover
        parser.error(f"unknown command: {args.command}")
    try:
        return int(handler(args))
    except AuthError as error:
        _dump({"ok": False, "auth_required": True, "error": str(error)})
        return 2
    except PipelineError as error:
        _dump({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
