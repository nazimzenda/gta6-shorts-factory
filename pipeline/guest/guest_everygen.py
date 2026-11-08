#!/usr/bin/env python3
"""Guest-side Everygen Shorts Studio driver (stdlib + selenium only).

Runs inside the Cua VM against the owner's signed-in everygen.ai session:

1. open Shorts Studio;
2. select the configured format (default ``GTA 6``);
3. put a direction derived from a discovered YouTube link into the prompt;
4. click Generate and approve the credit dialog when it appears;
5. wait for the completed result card;
6. open the result and download the MP4 to ``--download-dir``.

stdout is one JSON line:
    {"ok": true, "videos": [{"path": "...", "title": "...", "credits": 39}],
     "variant": 0, "error": null}

Exit codes: 0 ok, 1 error, 2 NOT_LOGGED_IN.
Everygen itself is never called through an API; only the visible web UI is
driven, and the session belongs to the owner.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

try:
    from selenium import webdriver
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:  # host-side import in tests
    webdriver = None
    ActionChains = None
    By = None
    Keys = None
    Options = None
    EC = None
    WebDriverWait = None

DEFAULT_WAIT = 20
HARD_DEADLINE = 1500
POLL_INTERVAL = 5
DOWNLOAD_WAIT = 120
MIN_VIDEO_BYTES = 50_000
JOB_DIR = os.environ.get("GTA_JOB_DIR", "/home/cua")
DOWNLOAD_DIR = "/home/cua/Downloads/everygen"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0"
)

LOGIN_MARKERS = (
    "log in to your account",
    "sign in with google",
    "create an account to reveal",
    "welcome back. enter your details",
)
LIMIT_MARKERS = (
    "insufficient credits",
    "not enough credits",
    "no credits",
    "credit limit",
    "limit reached",
    "daily limit",
    "quota exceeded",
    "upgrade to continue",
)
FAILURE_MARKERS = (
    "generation failed",
    "something went wrong",
    "couldn't generate",
    "could not generate",
    "try again",
)
PLAN_MARKERS = (
    "pick a plan to make this short",
    "choose a plan",
    "draft is saved",
    "upgrade to use",
    "get starter",
    "get pro",
    "get creator",
    "credits/mo",
    "start your plan",
)


class _DeadlineExceeded(BaseException):
    pass


def _hard_timeout(signum, frame):  # noqa: ARG001
    raise _DeadlineExceeded("hard deadline exceeded")


def _out(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def _log(message: str) -> None:
    print(f"[guest-everygen] {message}", file=sys.stderr, flush=True)


def _evidence_path(name: str) -> str:
    try:
        os.makedirs(JOB_DIR, exist_ok=True)
    except OSError:
        pass
    return os.path.join(JOB_DIR, name)


def _write_evidence(name: str, content: str) -> None:
    try:
        with open(_evidence_path(name), "w", encoding="utf-8") as handle:
            handle.write(content)
    except OSError:
        pass


def _screenshot(driver) -> None:
    try:
        driver.save_screenshot(_evidence_path("screenshot.png"))
    except Exception:
        pass


def _norm(text: str) -> str:
    return " ".join((text or "").replace("\u00a0", " ").split())


def _body_text(driver) -> str:
    try:
        return _norm(driver.find_element(By.TAG_NAME, "body").text)
    except Exception:
        return ""


def _lower_body(driver) -> str:
    return _body_text(driver).lower()


def _first(driver, selectors, timeout: int = DEFAULT_WAIT):
    for by, value in selectors:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except Exception:
            continue
    return None


def _first_visible(driver, selectors, timeout: int = DEFAULT_WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for by, value in selectors:
            try:
                elements = driver.find_elements(by, value)
            except Exception:
                continue
            for element in elements:
                try:
                    if element.is_displayed():
                        return element
                except Exception:
                    continue
        time.sleep(0.5)
    return None


def _click(driver, element) -> bool:
    try:
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click()", element)
            return True
        except Exception:
            return False


def _click_selector(driver, selectors, timeout: int = DEFAULT_WAIT) -> bool:
    element = _first_visible(driver, selectors, timeout=timeout)
    if element is None:
        return False
    return _click(driver, element)


def _visible_buttons(driver):
    try:
        return [element for element in driver.find_elements(By.TAG_NAME, "button") if element.is_displayed()]
    except Exception:
        return []


def _everygen_session_state(driver) -> bool | None:
    """Ask Everygen's own session endpoint (same-origin, cookie auth).

    Returns True (signed in), False (anonymous), or None when the probe could
    not run so the caller can fall back to the visible UI.
    """
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


def _plan_required(driver) -> bool:
    lowered = _lower_body(driver)
    return any(marker in lowered for marker in PLAN_MARKERS)


def _is_logged_in(driver) -> bool:
    session_state = _everygen_session_state(driver)
    if session_state is not None:
        return session_state
    lowered = _lower_body(driver)
    if any(marker in lowered for marker in LOGIN_MARKERS):
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
    url = (driver.current_url or "").lower()
    if "/signin" in url or "/login" in url:
        return False
    return True


def _prepare_browser(profile: str, download_dir: str):
    subprocess.run(["pkill", "-x", "firefox"])
    subprocess.run(["pkill", "-x", "firefox-bin"])
    subprocess.run(["pkill", "-x", "geckodriver"])
    time.sleep(2)
    try:
        os.remove(os.path.join(profile, ".parentlock"))
    except OSError:
        pass
    os.makedirs(download_dir, exist_ok=True)
    options = Options()
    options.add_argument("-profile")
    options.add_argument(profile)
    options.add_argument("--width=1366")
    options.add_argument("--height=900")
    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", download_dir)
    options.set_preference("browser.download.useDownloadDir", True)
    options.set_preference(
        "browser.helperApps.neverAsk.saveToDisk",
        "video/mp4,video/webm,video/quicktime,application/octet-stream",
    )
    options.set_preference("browser.download.manager.showWhenStarting", False)
    options.set_preference("browser.download.always_ask_before_handling_new_types", False)
    options.set_preference("media.volume_scale", "0.0")
    driver = webdriver.Firefox(options=options)
    driver.implicitly_wait(5)
    return driver


def _select_format(driver, wanted: str) -> bool:
    lowered = wanted.lower()
    try:
        chips = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Change format:"]')
        for chip in chips:
            if lowered in _norm(chip.text).lower() or lowered in (chip.get_attribute("aria-label") or "").lower():
                return True
    except Exception:
        pass

    opened = False
    if _click_selector(
        driver,
        [
            (By.CSS_SELECTOR, 'button[aria-label^="Select a format"]'),
            (By.CSS_SELECTOR, 'button[aria-label^="Choose format"]'),
            (By.XPATH, "//button[contains(., 'Choose format')]"),
        ],
        timeout=10,
    ):
        opened = True
    if opened:
        radios = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                radios = driver.find_elements(By.CSS_SELECTOR, 'div[role="radio"]')
            except Exception:
                radios = []
            if radios:
                break
            time.sleep(0.5)
        for radio in radios:
            try:
                text = _norm(radio.text).lower()
                if text.startswith(lowered) or f"\n{lowered}" in text:
                    return _click(driver, radio)
            except Exception:
                continue
        # Modal did not contain the wanted format; close it and try a template.
        _click_selector(driver, [(By.XPATH, "//button[normalize-space(.)='Close']")], timeout=3)

    # Template fallback: load a GTA 6 example card.  This also fills the prompt,
    # which the caller clears before typing its own direction.
    try:
        examples = driver.find_elements(
            By.XPATH,
            f"//button[contains(@aria-label, '{wanted}') and contains(@aria-label, 'Open this example')]",
        )
        for example in examples:
            if example.is_displayed():
                return _click(driver, example)
    except Exception:
        pass
    return False


def _current_format(driver) -> str:
    try:
        chips = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Change format:"]')
        if chips:
            return _norm(chips[0].text) or (
                chips[0].get_attribute("aria-label") or ""
            )
    except Exception:
        pass
    return ""


def _select_option(driver, prefix: str, wanted: str) -> bool:
    """Set a composer option such as quality (``720p``) or length (``10s``)."""
    try:
        buttons = driver.find_elements(
            By.CSS_SELECTOR, f'button[aria-label^="{prefix}"]'
        )
    except Exception:
        return False
    for button in buttons:
        try:
            if not button.is_displayed():
                continue
            if wanted.lower() in _norm(button.text).lower():
                return True
        except Exception:
            continue
    for button in buttons:
        try:
            if not button.is_displayed():
                continue
            if _click(driver, button):
                time.sleep(1)
                break
        except Exception:
            continue
    candidates = list(_visible_buttons(driver))
    for selector in ('[role="menuitem"]', '[role="option"]'):
        try:
            candidates.extend(driver.find_elements(By.CSS_SELECTOR, selector))
        except Exception:
            continue
    for candidate in candidates:
        try:
            if _norm(candidate.text).lower() == wanted.lower() and candidate.is_displayed():
                return _click(driver, candidate)
        except Exception:
            continue
    return False


def _prompt_element(driver):
    return _first_visible(
        driver,
        [
            (By.CSS_SELECTOR, '[data-slot="prompt-editor"]'),
            (By.CSS_SELECTOR, "textarea"),
            (By.CSS_SELECTOR, '[contenteditable="true"]'),
        ],
        timeout=15,
    )


def _clear_and_type(driver, element, text: str) -> bool:
    try:
        element.click()
    except Exception:
        pass
    try:
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.DELETE)
    except Exception:
        pass
    # Primary path: real keystrokes keep Tiptap/React state in sync.
    try:
        element.send_keys(text)
        time.sleep(1)
        if text[:40].lower() in _norm(element.text).lower():
            return True
    except Exception:
        pass
    # Fallback: execCommand insertText, which fires the browser input events
    # contenteditable editors listen for.
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            el.focus();
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            selection.removeAllRanges();
            selection.addRange(range);
            document.execCommand('insertText', false, arguments[1]);
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true, cancelable: true, inputType: 'insertText',
                data: arguments[1]
            }));
            """,
            element,
            text,
        )
        time.sleep(1)
        return text[:40].lower() in _norm(element.text).lower()
    except Exception:
        return False


def _generate_button(driver):
    candidates = []
    try:
        candidates = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label*="Generate"]')
    except Exception:
        return None
    for button in candidates:
        try:
            if button.is_displayed() and button.is_enabled():
                return button
        except Exception:
            continue
    return None


def _credits_from_button(button) -> float:
    try:
        label = button.get_attribute("aria-label") or button.text or ""
    except Exception:
        label = ""
    match = re.search(r"([\d,.]+)\s*credit", label, re.I)
    if not match:
        match = re.search(r"(\d{1,4})", label)
    if not match:
        return 0.0
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return 0.0


def _snapshot_results(driver) -> tuple[set[str], set[str]]:
    labels: set[str] = set()
    sources: set[str] = set()
    try:
        for button in driver.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Open video"]'):
            labels.add(button.get_attribute("aria-label") or "")
    except Exception:
        pass
    try:
        for video in driver.find_elements(By.TAG_NAME, "video"):
            src = video.get_attribute("currentSrc") or video.get_attribute("src") or ""
            if src:
                sources.add(src)
    except Exception:
        pass
    return labels, sources


def _result_cards(driver):
    try:
        return driver.find_elements(By.CSS_SELECTOR, '[data-result-card-frame="true"]')
    except Exception:
        return []


def _new_completed_card(driver, before_labels: set[str]):
    cards = _result_cards(driver)
    progress_markers = ("rendering", "generating", "queued", "processing")
    for card in reversed(cards):
        try:
            text = _norm(card.text).lower()
            status = ""
            try:
                status_element = card.find_element(By.CSS_SELECTOR, "[data-status]")
                status = (status_element.get_attribute("data-status") or "").lower()
            except Exception:
                pass
            open_button = None
            try:
                open_button = card.find_element(By.CSS_SELECTOR, 'button[aria-label^="Open video"]')
            except Exception:
                pass
            label = open_button.get_attribute("aria-label") if open_button else ""
            if label and label in before_labels:
                continue
            completed = status == "completed" or "completed" in text
            still_running = any(marker in text for marker in progress_markers)
            if completed or (label and not still_running):
                return card, open_button, label
        except Exception:
            continue
    return None


def _wait_for_result(
    driver, before_labels: set[str], timeout: int, auto_approve: bool = True
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lowered = _lower_body(driver)
        if any(marker in lowered for marker in LOGIN_MARKERS):
            return None, "NOT_LOGGED_IN"
        if any(marker in lowered for marker in PLAN_MARKERS):
            return None, "PLAN_REQUIRED"
        if any(marker in lowered for marker in LIMIT_MARKERS):
            return None, "LIMIT"
        dialog_error = _approve_dialog(driver, auto_approve=auto_approve)
        if dialog_error in {"NOT_LOGGED_IN", "LIMIT", "PLAN_REQUIRED", "APPROVAL_REQUIRED"}:
            return None, dialog_error
        card = _new_completed_card(driver, before_labels)
        if card:
            return card, None
        if any(marker in lowered for marker in FAILURE_MARKERS):
            if "generat" in lowered and "failed" in lowered:
                return None, "GENERATION_FAILED"
        time.sleep(POLL_INTERVAL)
    return None, "TIMEOUT"


def _approve_dialog(driver, auto_approve: bool = True) -> str | None:
    """Click the confirmation button in a credit/permission dialog, if any."""
    try:
        dialogs = [dialog for dialog in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]') if dialog.is_displayed()]
    except Exception:
        dialogs = []
    for dialog in dialogs:
        try:
            text = _norm(dialog.text).lower()
        except Exception:
            text = ""
        if any(marker in text for marker in LOGIN_MARKERS):
            return "NOT_LOGGED_IN"
        if any(marker in text for marker in PLAN_MARKERS):
            return "PLAN_REQUIRED"
        if any(marker in text for marker in LIMIT_MARKERS):
            return "LIMIT"
        buttons = []
        try:
            buttons = [button for button in dialog.find_elements(By.TAG_NAME, "button") if button.is_displayed()]
        except Exception:
            pass
        confirm = None
        for button in buttons:
            label = _norm(button.text).lower()
            aria = (button.get_attribute("aria-label") or "").lower()
            if label in {"cancel", "close", "not now", "later"}:
                continue
            if any(token in label or token in aria for token in ("generate", "confirm", "continue", "start", "approve", "yes")):
                confirm = button
                break
        if confirm is not None:
            if not auto_approve:
                return "APPROVAL_REQUIRED"
            if _click(driver, confirm):
                return None
    return None


def _candidate_download_controls(driver, scope=None):
    root = scope or driver
    selectors = [
        (By.XPATH, "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]"),
        (By.XPATH, "//a[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]"),
        (By.XPATH, "//a[@download]"),
        (By.XPATH, "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]"),
        (By.CSS_SELECTOR, 'a[href*=".mp4"], a[href*=".webm"]'),
    ]
    found = []
    for by, value in selectors:
        try:
            elements = root.find_elements(by, value)
        except Exception:
            continue
        for element in elements:
            try:
                if element.is_displayed() and element not in found:
                    found.append(element)
            except Exception:
                continue
    return found


def _menu_buttons(driver):
    selectors = (
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'more')]",
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'option')]",
        "//button[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'menu')]",
    )
    found = []
    for selector in selectors:
        try:
            found.extend(driver.find_elements(By.XPATH, selector))
        except Exception:
            continue
    return [element for element in found if element.is_displayed()]


def _snapshot_download_dir(directory: str) -> set[str]:
    try:
        return {name for name in os.listdir(directory)}
    except OSError:
        return set()


def _new_download(directory: str, before: set[str], timeout: int) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        for name in names:
            if name in before:
                continue
            path = os.path.join(directory, name)
            if name.endswith(".part"):
                continue
            try:
                if os.path.getsize(path) >= MIN_VIDEO_BYTES:
                    return path
            except OSError:
                continue
        time.sleep(2)
    return None


def _click_download_control(driver, element, output_path: str) -> bool:
    before = _snapshot_download_dir(DOWNLOAD_DIR)
    if not _click(driver, element):
        return False
    time.sleep(2)
    # A quality menu may appear; choose the first option.
    for button in _visible_buttons(driver):
        try:
            text = _norm(button.text).lower()
            if text in {"720p", "1080p", "original", "download"}:
                _click(driver, button)
                break
        except Exception:
            continue
    found = _new_download(DOWNLOAD_DIR, before, DOWNLOAD_WAIT)
    if not found:
        return False
    try:
        if os.path.abspath(found) != os.path.abspath(output_path):
            shutil.move(found, output_path)
        return os.path.getsize(output_path) >= MIN_VIDEO_BYTES
    except OSError:
        return False


def _video_sources(driver) -> list[str]:
    try:
        values = driver.execute_script(
            "return Array.from(document.querySelectorAll('video'))"
            ".map(v => v.currentSrc || v.src || '')"
            ".filter(Boolean)"
        )
        return list(dict.fromkeys(values or []))
    except Exception:
        return []


def _cookie_header(driver) -> str:
    try:
        cookies = driver.get_cookies()
    except Exception:
        return ""
    return "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name") and cookie.get("value")
    )


def _download_url(url: str, driver, output_path: str) -> bool:
    if url.startswith("data:"):
        try:
            header, data = url.split(",", 1)
            raw = base64.b64decode(data) if ";base64" in header else urllib.parse.unquote_to_bytes(data)
            with open(output_path, "wb") as handle:
                handle.write(raw)
            return os.path.getsize(output_path) >= MIN_VIDEO_BYTES
        except Exception:
            return False
    if url.startswith("blob:"):
        try:
            data_url = driver.execute_async_script(
                """
                const url = arguments[0];
                const done = arguments[arguments.length - 1];
                fetch(url, {credentials: 'include'}).then(r => r.blob()).then(blob => {
                    const reader = new FileReader();
                    reader.onloadend = () => done(reader.result);
                    reader.onerror = () => done('ERR');
                    reader.readAsDataURL(blob);
                }).catch(error => done('ERR:' + error));
                """,
                url,
            )
            if not isinstance(data_url, str) or not data_url.startswith("data:"):
                return False
            header, data = data_url.split(",", 1)
            raw = base64.b64decode(data) if ";base64" in header else urllib.parse.unquote_to_bytes(data)
            with open(output_path, "wb") as handle:
                handle.write(raw)
            return os.path.getsize(output_path) >= MIN_VIDEO_BYTES
        except Exception:
            return False
    if not url.startswith(("http://", "https://")):
        return False
    try:
        headers = {"User-Agent": USER_AGENT, "Referer": "https://everygen.ai/"}
        cookie = _cookie_header(driver)
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            with open(output_path, "wb") as handle:
                while chunk := response.read(1 << 20):
                    handle.write(chunk)
        return os.path.getsize(output_path) >= MIN_VIDEO_BYTES
    except Exception:
        return False


def _newest_window(driver) -> None:
    try:
        handles = driver.window_handles
        if len(handles) > 1:
            driver.switch_to.window(handles[-1])
            time.sleep(1)
    except Exception:
        pass


def _viewer_present(driver) -> bool:
    try:
        for dialog in driver.find_elements(By.CSS_SELECTOR, '[role="dialog"]'):
            if dialog.is_displayed():
                return True
    except Exception:
        pass
    try:
        for video in driver.find_elements(By.TAG_NAME, "video"):
            if video.is_displayed() and (
                video.get_attribute("currentSrc") or video.get_attribute("src")
            ):
                return True
    except Exception:
        pass
    return False


def _open_result(driver, card, open_button) -> None:
    target = open_button
    before_url = driver.current_url
    if target is None and card is not None:
        try:
            target = card.find_element(By.CSS_SELECTOR, 'button[aria-label^="Open video"]')
        except Exception:
            target = None
    if target is not None:
        _click(driver, target)
        time.sleep(3)
        _newest_window(driver)
        if _viewer_present(driver) or driver.current_url != before_url:
            return
    # The visible result card itself is clickable on some builds; the
    # accessibility button is pointer-events-none, so try the card too.
    if card is not None:
        _click(driver, card)
        time.sleep(3)
        _newest_window(driver)


def _collect_download(
    driver, card, open_button, output_path: str, before_sources: set[str]
) -> bool:
    """Try download controls, then the page's video URLs, then blob fetch."""
    _open_result(driver, card, open_button)
    if card is not None and ActionChains is not None:
        try:
            ActionChains(driver).move_to_element(card).perform()
            time.sleep(1)
        except Exception:
            pass
    controls = _candidate_download_controls(driver)
    if not controls:
        # Some result menus hide Download behind a "more" menu.
        for menu in _menu_buttons(driver)[:4]:
            _click(driver, menu)
            time.sleep(1)
            controls = _candidate_download_controls(driver)
            if controls:
                break
    for control in controls:
        href = ""
        try:
            href = control.get_attribute("href") or ""
        except Exception:
            href = ""
        if href and href.startswith(("http", "data:")) and not href.startswith("blob:"):
            if _download_url(href, driver, output_path):
                return True
        if _click_download_control(driver, control, output_path):
            return True

    # Fallback: use a video element that appeared after generation and was not
    # one of the page's example clips.
    for src in reversed(_video_sources(driver)):
        if not src or src in before_sources:
            continue
        if _download_url(src, driver, output_path):
            return True
    return False


def _parse_title(label: str, fallback: str) -> str:
    title = re.sub(r"^open video:\s*", "", (label or "").strip(), flags=re.I)
    return (title or fallback or "GTA 6 Short")[:160]


def main() -> int:
    parser = argparse.ArgumentParser(prog="guest_everygen.py")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--url", default="https://everygen.ai/tools/shorts-studio")
    parser.add_argument("--login-check", action="store_true")
    parser.add_argument("--format", default="GTA 6")
    parser.add_argument("--model", default="Seedance 2.5")
    parser.add_argument("--quality", default="720p")
    parser.add_argument("--duration", default="10s")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--direction", required=True)
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--budget-credits", type=float, default=0.0)
    parser.add_argument(
        "--manual-approval",
        action="store_false",
        dest="auto_approve",
        help="stop at the credit confirmation dialog instead of clicking it",
    )
    parser.add_argument("--timeout", type=int, default=HARD_DEADLINE)
    args = parser.parse_args()

    global DOWNLOAD_DIR
    DOWNLOAD_DIR = os.path.abspath(args.download_dir)
    os.environ.setdefault("DISPLAY", ":1")
    signal.signal(signal.SIGALRM, _hard_timeout)
    signal.alarm(min(int(args.timeout), HARD_DEADLINE))

    driver = None
    result: dict = {
        "ok": False,
        "videos": [],
        "variant": args.variant,
        "error": None,
        "note": "",
    }
    try:
        if webdriver is None:
            result["error"] = "selenium not installed"
            _out(result)
            return 1
        driver = _prepare_browser(args.profile, DOWNLOAD_DIR)
        driver.get(args.url)
        time.sleep(8)
        if not _is_logged_in(driver):
            result["error"] = "NOT_LOGGED_IN"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 2
        if _plan_required(driver):
            result["error"] = "PLAN_REQUIRED"
            result["note"] = "Everygen has no active plan or free credits"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1

        if not _select_format(driver, args.format):
            _log(f"format {args.format!r} not found in the picker")
        time.sleep(2)
        current_format = _current_format(driver)
        if args.format and args.format.lower() not in current_format.lower():
            result["error"] = "FORMAT_NOT_SELECTED"
            result["note"] = (
                f"wanted {args.format!r}, current format is "
                f"{current_format or 'unknown'!r}"
            )
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        # Best effort: the GTA 6 format already defaults to 720p/10s, but
        # honor explicit overrides when the composer exposes them.
        _select_option(driver, "Quality:", args.quality)
        _select_option(driver, "Clip length:", args.duration)
        time.sleep(1)

        prompt = _prompt_element(driver)
        if prompt is None:
            result["error"] = "prompt editor not found"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        if not _clear_and_type(driver, prompt, args.direction):
            result["error"] = "prompt text did not land"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        time.sleep(2)

        generate = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            generate = _generate_button(driver)
            if generate is not None:
                break
            time.sleep(1)
        if generate is None:
            if _plan_required(driver):
                result["error"] = "PLAN_REQUIRED"
                result["note"] = "Everygen has no active plan or free credits"
            else:
                result["error"] = "Generate button stayed disabled"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        credits = _credits_from_button(generate)
        result["credits"] = credits
        if args.budget_credits and credits and credits > args.budget_credits:
            result["error"] = "LIMIT"
            result["note"] = (
                f"clip costs {credits:.0f} credits, remaining budget is "
                f"{args.budget_credits:.0f}"
            )
            _out(result)
            return 0

        before_labels, before_sources = _snapshot_results(driver)
        if not _click(driver, generate):
            result["error"] = "could not click Generate"
            _screenshot(driver)
            _out(result)
            return 1
        time.sleep(2)
        dialog_error = _approve_dialog(driver, auto_approve=args.auto_approve)
        if dialog_error == "NOT_LOGGED_IN":
            result["error"] = "NOT_LOGGED_IN"
            _screenshot(driver)
            _out(result)
            return 2
        if dialog_error == "LIMIT":
            result["error"] = "LIMIT"
            _screenshot(driver)
            _out(result)
            return 0
        if dialog_error == "PLAN_REQUIRED":
            result["error"] = "PLAN_REQUIRED"
            result["note"] = "Everygen has no active plan or free credits"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        if dialog_error == "APPROVAL_REQUIRED":
            result["error"] = "APPROVAL_REQUIRED"
            result["note"] = "manual approval mode is on; approve the dialog in the VM"
            _screenshot(driver)
            _out(result)
            return 1

        card_info, wait_error = _wait_for_result(
            driver, before_labels, args.timeout, auto_approve=args.auto_approve
        )
        if wait_error:
            result["error"] = wait_error
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 2 if wait_error == "NOT_LOGGED_IN" else 0 if wait_error == "LIMIT" else 1

        card, open_button, label = card_info
        time.sleep(5)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_path = os.path.join(
            DOWNLOAD_DIR, f"everygen-v{args.variant}-{stamp}.mp4"
        )
        downloaded = _collect_download(
            driver, card, open_button, output_path, before_sources
        )
        if not downloaded and os.path.exists(output_path):
            downloaded = os.path.getsize(output_path) >= MIN_VIDEO_BYTES
        if not downloaded:
            result["error"] = "DOWNLOAD_FAILED"
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
            _out(result)
            return 1
        try:
            driver.save_screenshot(_evidence_path("screenshot.png"))
        except Exception:
            pass
        result.update(
            {
                "ok": True,
                "videos": [
                    {
                        "path": output_path,
                        "title": _parse_title(label, args.title),
                        "credits": credits,
                        "bytes": os.path.getsize(output_path),
                    }
                ],
                "error": None,
                "note": "downloaded from Everygen Shorts Studio",
            }
        )
        _out(result)
        return 0
    except _DeadlineExceeded:
        result["error"] = "TIMEOUT"
        if driver is not None:
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
        _out(result)
        return 1
    except Exception as error:  # noqa: BLE001
        result["error"] = f"{type(error).__name__}: {error}"[:1000]
        if driver is not None:
            _screenshot(driver)
            _write_evidence("page.html", driver.page_source or "")
        _out(result)
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
