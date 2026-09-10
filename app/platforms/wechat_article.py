"""公众号文章公开页指标采集。"""
from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class WechatArticleError(RuntimeError):
    pass


@dataclass
class WechatArticleMetrics:
    url: str
    title: str = ""
    read_count: int | None = None
    read_display: str = ""
    like_count: int | None = None
    share_count: int | None = None
    collect_count: int | None = None
    comment_count: int | None = None
    source: str = "public_page"


def normalize_article_url(value: str) -> str:
    raw = (value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or parsed.netloc.lower() != "mp.weixin.qq.com":
        raise WechatArticleError("请输入 mp.weixin.qq.com 的 https 文章链接")
    if not (parsed.path == "/s" or parsed.path.startswith("/s/")):
        raise WechatArticleError("请输入公众号文章链接")
    return urlunsplit(("https", "mp.weixin.qq.com", parsed.path, parsed.query, ""))


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _display_count(value: str) -> int | None:
    text = (value or "").strip().lower().replace(" ", "")
    if not text:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(万|w)?\+?", text)
    if not m:
        return None
    number = float(m.group(1))
    return int(number * 10_000) if m.group(2) else int(number)


def _first_number(value: Any, keys: tuple[str, ...]) -> int | None:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                number = _to_int(value[key])
                if number is not None:
                    return number
        for child in value.values():
            number = _first_number(child, keys)
            if number is not None:
                return number
    elif isinstance(value, list):
        for child in value:
            number = _first_number(child, keys)
            if number is not None:
                return number
    return None


def _extract_title(document: str) -> str:
    m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']*)', document, re.I)
    if not m:
        m = re.search(r"<title[^>]*>(.*?)</title>", document, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _extract_read_display(text: str) -> str:
    m = re.search(r"阅读\s*([0-9]+(?:\.\d+)?(?:万|w)?\+?)", text or "", re.I)
    return m.group(1) if m else ""


def parse_article_payload(url: str, document: str, *, body_text: str = "",
                          extension_payload: dict[str, Any] | None = None) -> WechatArticleMetrics:
    """Parse title plus metric fields supplied by getappmsgext or rendered page."""
    data = extension_payload or {}
    read_display = _extract_read_display(body_text)
    return WechatArticleMetrics(
        url=normalize_article_url(url),
        title=_extract_title(document),
        read_count=_first_number(data, ("read_num", "read_count")) or _display_count(read_display),
        read_display=read_display,
        # 公众号底部拇指图标使用 old_like_count；旧页面只提供 like_num 时兼容读取。
        like_count=_first_number(data, ("old_like_count", "like_num", "like_count")),
        share_count=_first_number(data, ("share_count",)),
        collect_count=_first_number(data, ("collect_count", "favorite_count")),
        comment_count=_first_number(data, ("comment_count",)),
        source="public_page_network" if extension_payload else "public_page",
    )


def _download_html(url: str) -> str:
    request = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


async def fetch_article_metrics(url: str) -> WechatArticleMetrics:
    """Fetch the public article page without sharing the monitor browser process."""
    article_url = normalize_article_url(url)
    document = await asyncio.to_thread(_download_html, article_url)
    return parse_article_payload(article_url, document)
