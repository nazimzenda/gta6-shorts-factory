#!/usr/bin/env python3
"""Guest-side TikTok uploader — self-contained (stdlib + selenium only).

Deployed to the Cua VM (as /home/cua/gta_pipeline/scripts/upload_tiktok.py), where a Firefox
profile holds a live TikTok session. This script NEVER logs in: any URL
containing "login" means the session is lost and we exit 2 so the host can
alert the owner instead of destroying the VM.

Verified DOM (2026-10-07 recon in the VM, tiktokstudio uploader):
- Entry: the left-nav <button aria-label="Upload"> navigates to the upload
  page (https://www.tiktok.com/tiktokstudio/upload). The header
  <div data-e2e="upload-icon"> is NOT selenium-clickable (scroll-into-view
  fails), so direct navigation to /upload is the fallback.
- File input: <input type="file" accept="video/*" style="display:none"> in
  the TOP frame (no iframe) — send_keys works on the hidden input.
- Processing cue: <div data-e2e="upload_status_container"> shows
  "Uploaded（1.6MB）" once the upload finishes.
- Caption editor: <div class="notranslate public-DraftEditor-content"
  role="combobox" contenteditable="true"> inside <div
  data-e2e="caption_container">. It AUTO-FILLS with the video filename, so
  we select-all before typing. Like Pinterest's DraftEditor it can silently
  drop typed text, so we read back the rendered text before Post.
- Post: <button data-e2e="post_video_button">; Discard: <button
  data-e2e="discard_post_button">.

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
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # pragma: no cover - host-side import only
    webdriver = None
    By = None
    Keys = None
    Options = None
    EC = None
    WebDriverWait = None

RESULT_PATH = "/home/cua/media/gta_pipeline/tiktok_result.png"
DEFAULT_WAIT = 10
MAX_WAIT = 30        # no WebDriverWait may exceed this
PROCESS_TIMEOUT = 60  # max wait for the upload to finish processing
HARD_DEADLINE = 540   # global SIGALRM: self-terminate instead of hanging forever


def is_logged_in_url(url: str) -> bool:
    """True when the TikTok session is alive: a tiktok.com URL with no
    'login' path (a login redirect means the session is lost)."""
    return ("tiktok.com" in url) and ("login" not in url.lower())


def click_first(driver, xpaths: list, timeout: int = DEFAULT_WAIT,
                attempts: int = 3) -> bool:
    """Try each XPath in order; click the first match. Never raises.

    The TikTok home feed is a React page that re-renders continuously, so a
    matched node can go stale before the click lands (verified 2026-10-07:
    WebDriverWait(element_to_be_clickable) lost the race every time). Each
    retry therefore does a FRESH lookup and falls back to a JS click, which
    shrinks the lookup→click window to milliseconds."""
    for xp in xpaths:
        for attempt in range(attempts):
            t = timeout if attempt == 0 else 2
            try:
                el = WebDriverWait(driver, t).until(
                    EC.presence_of_element_located((By.XPATH, xp)))
                try:
                    el.click()
                except Exception:
                    driver.execute_script("arguments[0].click()", el)
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


def _hard_timeout_handler(signum, frame):
    """SIGALRM handler: turn the hard deadline into a Python exception so the
    finally block still writes the error JSON + screenshot before exit."""
    raise TimeoutError(f"hard deadline exceeded after {HARD_DEADLINE}s")


def _norm_text(s: str) -> str:
    """Collapse all whitespace (incl. nbsp + newlines) so read-back comparison
    is robust to the DraftEditor's rendering."""
    return " ".join((s or "").replace("\u00a0", " ").split())


def _caption_landed(driver, el, expected: str, attempts: int = 5) -> bool:
    """Read back the DraftEditor text and check it contains the first 20
    chars of `expected`. innerText (via execute_script) is the PRIMARY
    read-back — Selenium's `.text` can stay empty for DraftEditor's rendered
    markup, so el.text is only the fallback. The editor re-renders async
    after send_keys, so retry briefly before declaring the caption lost."""
    want = _norm_text(expected)[:20]
    if not want:
        return True
    for _ in range(attempts):
        time.sleep(1)
        try:
            text = _norm_text(driver.execute_script(
                "return arguments[0].innerText", el) or "")
        except Exception:
            text = ""
        if not text:
            try:
                text = _norm_text(el.text or "")
            except Exception:
                text = ""
        if want in text:
            return True
    return False


def _post_confirmed(driver) -> bool:
    """True on any post-publish success cue: navigation away from the upload
    page, or the upload card resetting (select_video_container back /
    upload_status_container gone)."""
    if "upload" not in (driver.current_url or ""):
        return True
    if find_first(driver, [
            "//div[@data-e2e='select_video_container']"], timeout=1) is not None:
        return True
    return find_first(driver, [
        "//div[@data-e2e='upload_status_container']"], timeout=1) is None


def _out(live: bool, ok: bool, note: str, error) -> None:
    print(json.dumps({"ok": ok, "live": live, "note": note, "error": error}))


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="upload_tiktok.py",
        description="Upload a video to TikTok via the logged-in VM profile.")
    ap.add_argument("--profile", required=True, help="Firefox profile dir")
    ap.add_argument("--video", required=True, help="video file path")
    ap.add_argument("--caption", required=True,
                    help="caption text (title + hashtags)")
    ap.add_argument("--live", action="store_true",
                    help="actually publish; default stops before clicking Post")
    ap.add_argument("--timeout", type=int, default=240,
                    help="per-element wait timeout in seconds (capped at 30)")
    args = ap.parse_args()

    live = bool(args.live)
    wait = min(max(int(args.timeout), DEFAULT_WAIT), MAX_WAIT)
    os.environ.setdefault("DISPLAY", ":1")

    if webdriver is None:
        _out(live, False, "", "selenium not installed")
        return 1

    # Global hard deadline: SIGALRM -> TimeoutError so a hung step can't leave
    # the host polling forever with no JSON and no screenshot.
    signal.signal(signal.SIGALRM, _hard_timeout_handler)
    signal.alarm(HARD_DEADLINE)

    reported = False

    def report(ok: bool, note: str, error) -> None:
        nonlocal reported
        reported = True
        _out(live, ok, note, error)

    driver = None
    try:
        # Pre-launch hygiene: clear orphaned Firefox processes from a previous
        # timed-out run and drop the stale profile lock, or the launch hangs.
        # NOTE: `pkill -x firefox` (exact process-name match) — NOT
        # `pkill -f firefox`, which would match THIS script's own argv (the
        # --profile path contains "firefox") and kill the uploader itself.
        # The tarball Firefox on this VM also spawns a child whose process
        # name is `firefox-bin` (verified 2026-10-07: an orphan holding the
        # profile makes the new launch exit 0 immediately), so both names are
        # killed.
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

        driver.get("https://www.tiktok.com/")
        time.sleep(6)
        if not is_logged_in_url(driver.current_url or ""):
            report(False, "", "NOT_LOGGED_IN")
            return 2

        # 1. Upload entry. Verified DOM: <button aria-label="Upload"> in the
        #    left nav (an <a aria-label="Upload a video"> also matches). The
        #    home feed re-renders constantly, so click_first re-looks-up with
        #    a JS click. Direct navigation to /upload (stable URL; redirects
        #    to /tiktokstudio/upload) is the fallback when the click does not
        #    move us there.
        click_first(driver, [
            "//button[contains(translate(@aria-label,"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
            " 'upload')]",
            "//a[contains(translate(@aria-label,"
            " 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),"
            " 'upload')]"], timeout=wait)
        time.sleep(4)
        if "upload" not in (driver.current_url or ""):
            # Click did not navigate (overlay/menu or stale-click miss): go
            # directly to the Studio route. Verified 2026-10-13: /upload
            # serves a blank shell to cold automation clients while
            # /tiktokstudio/upload hydrates the form (file input present);
            # /upload redirects here anyway. 12s for VM software rendering.
            driver.get("https://www.tiktok.com/tiktokstudio/upload")
            time.sleep(12)
        if "upload" not in (driver.current_url or ""):
            report(False, "", f"not on upload page: {driver.current_url}")
            return 1

        # 2. File input (verified DOM: <input type="file" accept="video/*"
        #    style="display:none"> in the top frame). send_keys works on the
        #    hidden input.
        file_input = find_first(driver, [
            "//input[@type='file'][contains(@accept, 'video')]",
            "//input[@type='file']"], timeout=wait)
        if file_input is None:
            report(False, "", "file input not found")
            return 1
        file_input.send_keys(os.path.abspath(args.video))

        # 3. Processing wait (≤60s): the status card flips to
        #    "Uploaded（NMB）" when the upload finishes and the caption editor
        #    appears.
        deadline = time.monotonic() + PROCESS_TIMEOUT
        uploaded = False
        status_text = ""
        while time.monotonic() < deadline:
            status = find_first(driver, [
                "//div[@data-e2e='upload_status_container']"], timeout=2)
            if status is not None:
                try:
                    status_text = _norm_text(driver.execute_script(
                        "return arguments[0].innerText", status) or "")
                except Exception:
                    status_text = ""
                if "uploaded" in status_text.lower():
                    uploaded = True
                    break
            editor = find_first(driver, [
                "//div[@data-e2e='caption_container']"
                "//*[@contenteditable='true']",
                "//div[contains(@class, 'public-DraftEditor-content')]",
                "//*[@role='combobox'][@contenteditable='true']"], timeout=1)
            if editor is not None and status is None:
                uploaded = True  # older UI without a status card
                break
            time.sleep(2)
        if not uploaded:
            report(False, "",
                   f"upload processing timed out ({status_text or 'no status'})")
            return 1

        # 4. Caption. The editor auto-fills with the video FILENAME, so
        #    select-all (Ctrl+A) before typing. Read back the rendered text
        #    (DraftEditor can silently drop keystrokes) and refuse to Post if
        #    it did not land.
        caption = (args.caption or "")[:200]
        editor = find_first(driver, [
            "//div[@data-e2e='caption_container']//*[@contenteditable='true']",
            "//div[contains(@class, 'public-DraftEditor-content')]",
            "//*[@role='combobox'][@contenteditable='true']"], timeout=wait)
        if editor is None:
            report(False, "", "caption editor not found")
            return 1
        try:
            editor.click()
        except Exception:
            pass
        if caption:
            editor.send_keys(Keys.CONTROL, "a")
            editor.send_keys(caption)
            if not _caption_landed(driver, editor, caption):
                report(False, "", "caption did not land (DraftEditor)")
                return 1

        # 5. Post — only in live mode. Verified DOM: <button
        #    data-e2e="post_video_button">.
        if live:
            if not click_first(driver, [
                    "//button[@data-e2e='post_video_button']"], timeout=wait):
                report(False, "", "post button not found")
                return 1
            # Copyright-check interstitial (verified 2026-10-13 screenshot):
            # TikTok pops "Continue to post? … [Cancel] [Post now]" when the
            # content check is still running. Confirm through it; absence is
            # fine (direct posts skip the modal).
            try:
                click_first(driver, [
                    "//button[contains(., 'Post now')]",
                    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    " 'abcdefghijklmnopqrstuvwxyz'), 'post now')]"],
                    timeout=15)
            except Exception:
                pass
            try:  # ≤20s for any success cue
                WebDriverWait(driver, 20).until(
                    lambda d: _post_confirmed(d))
                confirmed = True
            except Exception:
                confirmed = False
            if not confirmed:
                report(False, "", "post did not confirm — check screenshot")
                return 1
            time.sleep(4)
            report(True, "uploaded", None)
            return 0

        # 6. Dry-run report. The screenshot is taken in `finally` so a failure
        #    frame is captured on EVERY exit path before the browser quits.
        time.sleep(4)
        report(True, "dry-run stopped before Post", None)
        return 0
    except Exception as e:
        report(False, "", str(e))
        return 1
    finally:
        signal.alarm(0)
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
        # Safety net: if the alarm fired outside the try (or mid-exit), emit
        # the error JSON here — guarded so it never double-prints.
        if not reported:
            report(False, "", "hard deadline exceeded")


if __name__ == "__main__":
    sys.exit(main())
