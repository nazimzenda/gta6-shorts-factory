#!/usr/bin/env python3
"""Guest-side YouTube Studio uploader — self-contained (stdlib + selenium only).

Deployed to the Cua VM (as /home/cua/gta_pipeline/scripts/upload_yt.py), where a Firefox profile
holds a live YouTube Studio session. This script NEVER logs in: a redirect to
an accounts.google.com URL means the session is lost and we exit 2 so the
host can alert the owner instead of destroying the VM.

stdout: a single JSON line {"ok", "live", "note", "error"}.
exit codes: 0 ok, 1 error, 2 NOT_LOGGED_IN.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

# Guarded import: on the host (tests) selenium is not installed; the guest
# venv always has it. The pure function is_logged_in_url must import cleanly
# everywhere.
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - host-side import only
    webdriver = None
    By = None
    Options = None
    EC = None
    WebDriverWait = None

RESULT_PATH = "/home/cua/media/gta_pipeline/yt_result.png"
DEFAULT_WAIT = 10
HARD_DEADLINE = 840    # whole-run cap; must stay below the host poll (900s)
CONFIRM_TIMEOUT = 75   # post-publish confirmation window (60-90s)
CONFIRM_SAFETY = 20    # reserved inside HARD_DEADLINE for report + screenshot
CLEANUP_GUARD = 20     # hard bound on the finally screenshot/quit
SAVE_WAIT = 8          # short wait for the visibility step's Save/Publish

# Visibility radio lives only on the final wizard step. The same list backs
# _select_public() and _public_is_selected().
_PUBLIC_XPATHS = [
    "//tp-yt-paper-radio-button[@name='PUBLIC']",
    "//tp-yt-paper-radio-button[contains(., 'Public')]",
    "//div[@id='radioContainer']//tp-yt-paper-radio-button"
    "[.//*[contains(text(), 'Public')]]",
]
_NEXT_XPATHS = [
    "//button[contains(., 'Next')]",
    "//ytcp-button[contains(., 'Next')]",
]
_SAVE_XPATHS = [
    "//button[contains(., 'Save')]",
    "//ytcp-button[contains(., 'Save')]",
    "//button[contains(., 'Publish')]",
    "//ytcp-button[contains(., 'Publish')]",
]


def is_logged_in_url(url: str) -> bool:
    """True when the YouTube Studio session is alive: studio.youtube.com
    without an accounts.google.com login redirect."""
    return ("accounts.google.com" not in url) and ("studio.youtube.com" in url)


def _is_login_redirect(url: str) -> bool:
    """True when the browser has been bounced to a Google sign-in page."""
    u = (url or "").lower()
    return ("accounts.google.com" in u) or ("/signin" in u)


def _publish_confirmed(url: str, page_source: str) -> bool:
    """True ONLY on positive publish evidence.

    Either the Studio success dialog ("Video published" / "... is now live"),
    or a public youtube.com/watch URL. A studio.youtube.com/video/<id>/edit
    URL is the auto-saved PRIVATE DRAFT destination — Studio lands there as
    soon as the upload exists, before Publish is ever clicked — so it is
    never proof. Generic "Upload complete" is also deliberately not proof:
    it can render while the upload still sits on the Publish button.
    """
    src = (page_source or "").lower()
    if "video published" in src or "is now live" in src:
        return True
    return "youtube.com/watch" in (url or "").lower()


def _public_is_selected(driver) -> bool:
    """True only when the PUBLIC radio reports itself checked.

    Reads aria-checked/checked back after the click; an absent or unreadable
    radio is NOT treated as selected — a private publish is never allowed to
    slip through silently. "xpath" is By.XPATH, written literally so the
    helper stays callable in host-side tests where selenium is absent.
    """
    for xp in _PUBLIC_XPATHS:
        try:
            elements = driver.find_elements("xpath", xp)
        except Exception:
            continue
        for el in elements:
            try:
                if str(el.get_attribute("aria-checked") or "").lower() == "true":
                    return True
                checked = el.get_attribute("checked")
                if str(checked).lower() in ("true", "1", "checked"):
                    return True
            except Exception:
                continue
    return False


class _DeadlineExceeded(BaseException):
    """Raised by the SIGALRM handler when the whole-run cap expires.

    BaseException keeps the broad ``except Exception`` handlers in the click
    helpers from swallowing the deadline and continuing to publish.
    """


def _hard_timeout_handler(signum, frame):
    raise _DeadlineExceeded("timeout")


def click_first(driver, xpaths: list, timeout: int = DEFAULT_WAIT) -> bool:
    """Try each XPath in order; click the first clickable match. Never raises."""
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, xp)))
            el.click()
            return True
        except Exception:
            continue
    return False


def find_first(driver, xpaths: list, timeout: int = DEFAULT_WAIT):
    """Return the first present element matching any XPath, or None."""
    for xp in xpaths:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xp)))
        except Exception:
            continue
    return None


def _out(live: bool, ok: bool, note: str, error) -> None:
    print(json.dumps({"ok": ok, "live": live, "note": note, "error": error}),
          flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="upload_yt.py",
        description="Upload a video to YouTube Studio via the logged-in VM profile.")
    ap.add_argument("--profile", required=True, help="Firefox profile dir")
    ap.add_argument("--video", required=True, help="video file path")
    ap.add_argument("--title", required=True, help="video title")
    ap.add_argument("--description", default=None)
    ap.add_argument("--live", action="store_true",
                    help="actually publish; default stops at the review screen")
    ap.add_argument("--timeout", type=int, default=240,
                    help="per-element wait timeout in seconds")
    args = ap.parse_args()

    live = bool(args.live)
    wait = max(int(args.timeout), DEFAULT_WAIT)
    os.environ.setdefault("DISPLAY", ":1")

    if webdriver is None:
        _out(live, False, "", "selenium not installed")
        return 1

    # Whole-run hard deadline: SIGALRM -> _DeadlineExceeded so a hung step
    # cannot outlive the host's 900s poll with no JSON and no screenshot.
    # deadline_epoch also budgets the post-publish confirmation window.
    deadline_epoch = time.time() + HARD_DEADLINE
    publish_attempted = False
    signal.signal(signal.SIGALRM, _hard_timeout_handler)
    signal.alarm(HARD_DEADLINE)

    driver = None
    try:
        # Pre-launch hygiene: clear orphaned Firefox processes from a previous
        # timed-out run and drop the stale profile lock, or the launch hangs.
        # NOTE: `pkill -x firefox` (exact process-name match) — NOT
        # `pkill -f firefox`, which would match THIS script's own argv (the
        # --profile path contains "firefox") and kill the uploader itself.
        subprocess.run(["pkill", "-x", "firefox"])
        subprocess.run(["pkill", "-x", "firefox-bin"])
        subprocess.run(["pkill", "-x", "geckodriver"])
        time.sleep(2)
        try:
            os.remove(os.path.join(args.profile, ".parentlock"))
        except OSError:
            pass

        opts = Options()
        opts.add_argument("-profile")
        opts.add_argument(args.profile)
        opts.add_argument("--width=1366")
        opts.add_argument("--height=900")
        driver = webdriver.Firefox(options=opts)
        driver.implicitly_wait(10)

        # 2. Open Studio; a redirect to accounts.google.com = logged-out session.
        driver.get("https://studio.youtube.com")
        time.sleep(8)
        if not is_logged_in_url(driver.current_url or ""):
            _out(live, False, "", "NOT_LOGGED_IN")
            return 2

        # 3. Create (verified DOM: <button aria-label="Create"> plus a
        #    <ytcp-button class="ytcpAppHeaderCreateIcon"> twin)
        if not click_first(driver, [
                "//button[@aria-label='Create']",
                "//button[contains(., 'Create')]",
                "//ytcp-button[contains(., 'Create')]"], timeout=wait):
            _out(live, False, "", "could not find Create button")
            return 1

        # 4. Upload videos (verified DOM: the menu item leaf is a
        #    <yt-formatted-string class="item-text main-text"> inside
        #    ytcp-text-menu; the container div also contains the text, so we
        #    click the exact-text leaf first)
        if not click_first(driver, [
                "//yt-formatted-string[normalize-space(text())='Upload videos']",
                "//button[contains(., 'Upload videos')]",
                "//ytcp-button[contains(., 'Upload videos')]",
                "//*[@role='menuitem'][contains(., 'Upload videos')]"],
                timeout=wait):
            _out(live, False, "", "could not find Upload videos menu item")
            return 1

        # 5. File input
        file_input = find_first(driver, ["//input[@type='file']"], timeout=wait)
        if file_input is None:
            _out(live, False, "", "file input not found")
            return 1
        file_input.send_keys(os.path.abspath(args.video))
        time.sleep(10)  # processing

        # 6. Title (verified DOM: <div id="textbox" contenteditable="true"
        #    role="textbox"> inside <ytcp-social-suggestions-textbox
        #    id="title-textarea"> — a div, NOT an input)
        title_el = find_first(driver, [
            "//*[@id='title-textarea']//*[@contenteditable='true']",
            "//div[@id='textbox'][@contenteditable='true']",
            "//*[@aria-label='Add a title that describes your video "
            "(type @ to mention a channel)']"], timeout=wait)
        if title_el is None:
            _out(live, False, "", "title field not found")
            return 1
        try:
            title_el.clear()
        except Exception:
            pass
        title_el.send_keys((args.title or "")[:100])

        # 7. Description (verified DOM: the id lives on the custom
        #    <ytcp-social-suggestions-textbox id="description-textarea"> tag;
        #    the editable field is its inner <div id="textbox"
        #    contenteditable="true">)
        if args.description:
            desc_el = find_first(driver, [
                "//*[@id='description-textarea']//*[@contenteditable='true']",
                "//*[@aria-label='Tell viewers about your video "
                "(type @ to mention a channel)']",
                "//div[@id='description-container']//*[@contenteditable='true']"],
                timeout=wait)
            if desc_el is None:
                _out(live, False, "", "description field not found")
                return 1
            desc_el.send_keys(args.description[:500])

        # 8. Walk dialogs. Live mode is a deterministic stepper:
        #    Next → (Checks: answer NOT_MFK) → Next → (Visibility: select
        #    PUBLIC, verify it, then Save/Publish). Verified 2026-10-13:
        #    visibility defaults to PRIVATE and the owner wants every Short
        #    PUBLIC, so Save is only allowed once the radio reads back
        #    checked — a private publish is worse than a loud failure.
        #    Dry-run NEVER clicks Publish/Save — only Next (max 3), then
        #    stops on the review screen.

        def _answer_audience():
            try:
                el = find_first(driver, [
                    "//tp-yt-paper-radio-button[@name='VIDEO_MADE_FOR_KIDS_NOT_MFK']",
                    "//tp-yt-paper-radio-button[contains(., 'not made for kids')]"],
                    timeout=8)
                if el is not None:
                    driver.execute_script("arguments[0].scrollIntoView(true);", el)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    return True
            except Exception:
                pass
            return False

        def _select_public():
            try:
                el = find_first(driver, _PUBLIC_XPATHS, timeout=8)
                if el is not None:
                    driver.execute_script("arguments[0].scrollIntoView(true);", el)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(2)
                    return True
            except Exception:
                pass
            return False

        def _wait_public_selected(attempts: int = 5) -> bool:
            for _ in range(attempts):
                if _public_is_selected(driver):
                    return True
                time.sleep(1)
            return False

        if live:
            saved = False
            for _ in range(6):
                time.sleep(3)
                try:
                    current_url = driver.current_url or ""
                except Exception:
                    current_url = ""
                if _is_login_redirect(current_url):
                    _out(live, False, "", "NOT_LOGGED_IN")
                    return 2
                _answer_audience()
                radio_found = _select_public()
                public_ok = _public_is_selected(driver)
                if radio_found and not public_ok:
                    public_ok = _wait_public_selected()
                if public_ok:
                    # Visibility step: this button is Save/Publish, not Next.
                    # Try it with the SHORT timeout before waiting on Next.
                    if click_first(driver, _SAVE_XPATHS, timeout=SAVE_WAIT):
                        saved = True
                        publish_attempted = True
                        break
                    continue  # button rendered late; retry on the next pass
                if radio_found:
                    break  # PUBLIC exists but will not check — never save
                if click_first(driver, _NEXT_XPATHS, timeout=wait):
                    continue
                break
            if not saved:
                _out(live, False, "", "PUBLIC could not be selected")
                return 1
        else:
            next_clicks = 0
            for _ in range(4):
                time.sleep(3)
                if next_clicks >= 3:
                    break
                if click_first(driver, _NEXT_XPATHS, timeout=wait):
                    next_clicks += 1
                    continue
                break  # review screen reached

        # 9. Report. The screenshot is taken in `finally` so a failure frame
        #    is captured on EVERY exit path before the browser quits.
        if live:
            # Settle + confirmation must fit inside the whole-run deadline: a
            # genuine publish must not be misreported as a generic timeout
            # because the confirmation window pushed past HARD_DEADLINE.
            settle = min(5, max(
                0, int(deadline_epoch - time.time() - CONFIRM_SAFETY)))
            time.sleep(settle)
            confirm_window = min(
                CONFIRM_TIMEOUT,
                max(0, int(deadline_epoch - time.time() - CONFIRM_SAFETY)))
            # Positive evidence only: success dialog text, or a public
            # youtube.com/watch URL. A Studio /edit URL is the private draft.
            confirmed = False
            for _ in range(confirm_window):
                try:
                    current_url = driver.current_url or ""
                    page_source = driver.page_source or ""
                except Exception:
                    time.sleep(1)
                    continue
                if _is_login_redirect(current_url):
                    _out(live, False, "", "NOT_LOGGED_IN")
                    return 2
                if _publish_confirmed(current_url, page_source):
                    confirmed = True
                    break
                time.sleep(1)
            if not confirmed:
                _out(live, False, "", "publish attempted but unconfirmed")
                return 1
            _out(live, True, "uploaded", None)
            return 0
        time.sleep(5)
        _out(live, True, "dry-run stopped at review", None)
        return 0
    except _DeadlineExceeded:
        if publish_attempted:
            _out(live, False, "", "publish attempted but unconfirmed")
        else:
            _out(live, False, "", "timeout")
        return 1
    except Exception as e:
        _out(live, False, "", str(e))
        return 1
    finally:
        # Keep an alarm armed through the screenshot/quit: either can block,
        # and SIGALRM is one-shot, so re-arm what is left of the budget (or a
        # short guard once the deadline already fired) instead of cancelling.
        remaining = int(deadline_epoch - time.time())
        signal.alarm(remaining if remaining > 0 else CLEANUP_GUARD)
        try:
            if driver is not None:
                try:
                    os.makedirs(os.path.dirname(RESULT_PATH), exist_ok=True)
                    driver.save_screenshot(RESULT_PATH)
                except Exception:
                    pass
                try:
                    driver.quit()
                except Exception:
                    pass
        except _DeadlineExceeded:
            pass  # cleanup guard fired; the result JSON is already flushed
        finally:
            signal.alarm(0)


if __name__ == "__main__":
    sys.exit(main())
