"""Discover GTA 6 YouTube links without API keys.

YouTube's public search page embeds the same ``ytInitialData`` payload its own
frontend uses.  We parse that JSON, keep video metadata, and rank recent +
watched results.  No account, cookie, OAuth token or API key is involved.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Iterable

LOGGER = logging.getLogger("pipeline.yt_search")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
VIDEOS_FILTER = "EgIQAQ%3D%3D"
SHORTS_FILTER = "EgIYAQ%3D%3D"
_INITIAL_DATA_RE = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S)


@dataclass(frozen=True)
class VideoLink:
    url: str
    video_id: str
    title: str
    channel: str = ""
    duration: str = ""
    view_count: str = ""
    published: str = ""
    query: str = ""
    is_short: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def _initial_data(html: str) -> dict[str, Any]:
    match = _INITIAL_DATA_RE.search(html or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    if isinstance(value.get("simpleText"), str):
        return value["simpleText"]
    runs = value.get("runs")
    if isinstance(runs, list):
        return "".join(
            str(run.get("text", "")) for run in runs if isinstance(run, dict)
        )
    return ""


def _walk(node: Any, key: str) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        if key in node and isinstance(node[key], dict):
            yield node[key]
        for value in node.values():
            yield from _walk(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value, key)


def _is_short_renderer(video: dict[str, Any]) -> bool:
    navigation = (
        video.get("navigationEndpoint", {})
        .get("commandMetadata", {})
        .get("webCommandMetadata", {})
    )
    url = str(navigation.get("url") or "")
    if "/shorts/" in url:
        return True
    for overlay in video.get("thumbnailOverlays") or []:
        if not isinstance(overlay, dict):
            continue
        style = (
            overlay.get("thumbnailOverlayTimeStatusRenderer", {}).get("style", "")
        )
        if str(style).upper() == "SHORTS":
            return True
    return False


def parse_search_html(html: str, query: str = "") -> list[VideoLink]:
    """Extract video entries from one YouTube results page."""
    data = _initial_data(html)
    if not data:
        return []
    results: list[VideoLink] = []
    seen: set[str] = set()
    for video in _walk(data, "videoRenderer"):
        video_id = str(video.get("videoId") or "").strip()
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        title = _text(video.get("title")) or _text(video.get("headline"))
        if not title:
            continue
        channel = ""
        owner = video.get("ownerText") or video.get("longBylineText")
        if isinstance(owner, dict):
            runs = owner.get("runs")
            if isinstance(runs, list) and runs and isinstance(runs[0], dict):
                channel = str(runs[0].get("text") or "")
            else:
                channel = _text(owner)
        length = _text(video.get("lengthText"))
        views = _text(video.get("viewCountText"))
        published = _text(video.get("publishedTimeText"))
        is_short = _is_short_renderer(video)
        path = "shorts" if is_short else "watch"
        url = (
            f"https://www.youtube.com/{path}/{video_id}"
            if is_short
            else f"https://www.youtube.com/watch?v={video_id}"
        )
        results.append(
            VideoLink(
                url=url,
                video_id=video_id,
                title=title.strip(),
                channel=channel.strip(),
                duration=length,
                view_count=views,
                published=published,
                query=query,
                is_short=is_short,
            )
        )
    return results


def search(
    query: str,
    *,
    limit: int = 20,
    timeout: int = 25,
    shorts: bool = False,
) -> list[VideoLink]:
    """Search YouTube once and return up to ``limit`` video links."""
    params = {"search_query": query}
    if shorts:
        params["sp"] = SHORTS_FILTER
    else:
        params["sp"] = VIDEOS_FILTER
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode(params)
    try:
        html = _get(url, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        LOGGER.warning("YouTube search failed for %r: %s", query, error)
        return []
    results = parse_search_html(html, query)
    if shorts:
        results = [item for item in results if item.is_short] or results
    return results[: max(0, limit)]


def views_to_int(text: str) -> int:
    """Parse ``"1.2M views"`` / ``"74,897,829 views"`` into an integer."""
    raw = (text or "").lower().replace(",", "").strip()
    match = re.search(r"([\d.]+)\s*([kmb])?", raw)
    if not match:
        return 0
    value = float(match.group(1))
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(
        match.group(2) or "", 1
    )
    return int(value * multiplier)


def age_hours(text: str) -> float:
    """Parse ``"3h ago"`` / ``"2mo ago"`` into hours (best effort)."""
    raw = (text or "").lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(s|mo|m|h|d|w|y)", raw)
    if not match:
        return 24 * 365
    value = float(match.group(1))
    unit = match.group(2)
    factor = {
        "s": 1 / 3600,
        "m": 1 / 60,
        "h": 1,
        "d": 24,
        "w": 24 * 7,
        "mo": 24 * 30,
        "y": 24 * 365,
    }[unit]
    return value * factor


def relevance_score(link: VideoLink) -> float:
    """Favor watched + fresh results without letting a 2-year trailer dominate."""
    views = views_to_int(link.view_count)
    age = max(1.0, age_hours(link.published))
    return views / (age + 24.0)


def discover(
    queries: Iterable[str],
    *,
    per_query: int = 20,
    min_views: int = 0,
    timeout: int = 25,
    sleep_range: tuple[float, float] = (1.0, 2.5),
) -> list[VideoLink]:
    """Search every configured query, dedupe, filter and rank."""
    combined: dict[str, VideoLink] = {}
    for query in queries:
        links = search(query, limit=per_query, timeout=timeout)
        for link in links:
            if views_to_int(link.view_count) < min_views:
                continue
            current = combined.get(link.video_id)
            if current is None or relevance_score(link) > relevance_score(current):
                combined[link.video_id] = link
        time.sleep(random.uniform(*sleep_range))
    return sorted(combined.values(), key=relevance_score, reverse=True)
