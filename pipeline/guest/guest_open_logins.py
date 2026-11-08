#!/usr/bin/env python3
"""Open the owner's signed-in sites in the Cua VM and leave Firefox running.

This is the preparation step: the owner signs in manually through the CUA
viewer, then the pipeline can drive the same profile.  No credentials touch
this script.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

SITES = (
    "https://studio.youtube.com",
    "https://www.tiktok.com/tiktokstudio/upload",
    "https://everygen.ai/tools/shorts-studio",
)


def _out(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _firefox_running() -> bool:
    for name in ("firefox", "firefox-bin"):
        if subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(prog="guest_open_logins.py")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    os.environ.setdefault("DISPLAY", ":1")
    urls = list(SITES)
    try:
        running = _firefox_running()
        if running:
            # Reuse the existing instance so the owner keeps current tabs.
            command = ["firefox", "-profile", args.profile, *urls]
            subprocess.run(command, timeout=30, check=False)
            mode = "new_tabs"
        else:
            # Drop a stale profile lock from a killed automation run.
            try:
                os.remove(os.path.join(args.profile, ".parentlock"))
            except OSError:
                pass
            command = [
                "firefox",
                "-profile",
                args.profile,
                "-no-remote",
                *urls,
            ]
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":1")},
            )
            mode = "started"
        time.sleep(6)
        _out(
            {
                "ok": True,
                "mode": mode,
                "urls": urls,
                "note": (
                    "Sign in to YouTube Studio, TikTok Studio and everygen.ai in "
                    "the CUA viewer. The pipeline never asks for passwords."
                ),
            }
        )
        return 0
    except Exception as error:  # noqa: BLE001
        _out({"ok": False, "error": str(error)[:1000]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
