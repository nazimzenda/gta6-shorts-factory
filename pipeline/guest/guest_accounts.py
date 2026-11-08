#!/usr/bin/env python3
"""Guest-side account check for the Cua VM (stdlib + selenium only).

Reports whether the owner's Firefox profile still has live sessions for
YouTube Studio, TikTok Studio and Everygen.  It NEVER logs in and never reads
or stores credentials.  Exit code 0 means the check ran; the JSON payload
carries the per-site ``logged_in`` flags.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
except ImportError:  # host-side import in tests
    webdriver = None
    By = None
    Options = None

HARD_DEADLINE = 300
JOB_DIR = os.environ.get("GTA_JOB_DIR", "/home/cua")


def _write_evidence(name: str, content: str) -> None:
    try:
        os.makedirs(JOB_DIR, exist_ok=True)
        with open(os.path.join(JOB_DIR, name), "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError:
        pass


def _out(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _hard_timeout(signum, frame):  # noqa: ARG001
    raise TimeoutError("account check hard deadline exceeded")


def _prepare_profile(profile: str) -> None:
    subprocess.run(["pkill", "-x", "firefox"])
    subprocess.run(["pkill", "-x", "firefox-bin"])
    subprocess.run(["pkill", "-x", "geckodriver"])
    time.sleep(2)
    try:
        os.remove(os.path.join(profile, ".parentlock"))
    except OSError:
        pass


def _visible_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return ""


def _everygen_session_state(driver) -> bool | None:
    try:
        result = driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            fetch('/api/auth/get-session', {credentials: 'include'})
              .then(r => r.text().then(text => done({status: r.status, body: text})))
              .catch(error => done({status: 0, body: String(error)}));
            """
        )
    except Exception:
        return None
    if not isinstance(result, dict) or result.get("status") != 200:
        return None
    try:
        body = json.loads(result.get("body") or "null")
    except ValueError:
        return None
    if body is None:
        return False
    if isinstance(body, dict):
        return bool(body.get("session") or body.get("user"))
    return False


def _everygen_logged_in(driver) -> bool:
    session_state = _everygen_session_state(driver)
    if session_state is not None:
        return session_state
    url = (driver.current_url or "").lower()
    if "/signin" in url or "/login" in url:
        return False
    source = (driver.page_source or "").lower()
    if "log in to your account" in source or "create an account to reveal" in source:
        return False
    try:
        buttons = driver.find_elements(By.XPATH, "//button[normalize-space(.)='Sign in']")
        for button in buttons:
            try:
                if button.is_displayed():
                    return False
            except Exception:
                continue
    except Exception:
        pass
    return "everygen" in url


def main() -> int:
    parser = argparse.ArgumentParser(prog="guest_accounts.py")
    parser.add_argument("--profile", required=True)
    parser.add_argument(
        "--everygen-url", default="https://everygen.ai/tools/shorts-studio"
    )
    args = parser.parse_args()
    os.environ.setdefault("DISPLAY", ":1")
    signal.signal(signal.SIGALRM, _hard_timeout)
    signal.alarm(HARD_DEADLINE)
    _prepare_profile(args.profile)

    accounts = {
        "youtube": {"logged_in": False, "url": "", "error": None},
        "tiktok": {"logged_in": False, "url": "", "error": None},
        "everygen": {"logged_in": False, "url": "", "error": None},
    }
    driver = None
    try:
        if webdriver is None:
            _out({"ok": False, "accounts": accounts, "error": "selenium not installed"})
            return 1
        options = Options()
        options.add_argument("-profile")
        options.add_argument(args.profile)
        options.add_argument("--width=1366")
        options.add_argument("--height=900")
        driver = webdriver.Firefox(options=options)
        driver.implicitly_wait(5)

        checks = (
            ("youtube", "https://studio.youtube.com"),
            ("tiktok", "https://www.tiktok.com/tiktokstudio/upload"),
            ("everygen", args.everygen_url),
        )
        for name, url in checks:
            try:
                driver.get(url)
                time.sleep(8)
                current = driver.current_url or ""
                if name == "youtube":
                    logged = (
                        "accounts.google.com" not in current
                        and "studio.youtube.com" in current
                    )
                elif name == "tiktok":
                    logged = "tiktok.com" in current and "login" not in current.lower()
                else:
                    logged = _everygen_logged_in(driver)
                accounts[name] = {
                    "logged_in": bool(logged),
                    "url": current,
                    "title": driver.title,
                    "error": None,
                }
                _write_evidence(
                    f"{name}.html", driver.page_source or ""
                )
            except Exception as error:  # noqa: BLE001 - report per site
                accounts[name] = {
                    "logged_in": False,
                    "url": "",
                    "title": "",
                    "error": str(error)[:400],
                }
        try:
            driver.save_screenshot(os.path.join(JOB_DIR, "screenshot.png"))
        except Exception:
            pass
        ok = all(item.get("logged_in") for item in accounts.values())
        _out({"ok": ok, "accounts": accounts, "error": None})
        return 0
    except Exception as error:  # noqa: BLE001
        _out({"ok": False, "accounts": accounts, "error": str(error)[:1000]})
        return 1
    finally:
        signal.alarm(0)
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
