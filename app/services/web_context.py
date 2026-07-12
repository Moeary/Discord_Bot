from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.core.config import EnvSettings


LOGGER = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?)]}，。；：！？）】》"
SEARCH_PREFIX_RE = re.compile(
    r"(?:^|\s)(?:搜索|搜一下|查一下|帮我查|网上查|联网查|查查|search|google|bing)\s*[:：]?\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)
SEARCH_CUE_RE = re.compile(
    r"(最新|当前|实时|新闻|价格|股价|汇率|天气|官网|下载|版本|发布|比赛|赛程|release|latest|current|recent|news|price|weather|version)",
    re.IGNORECASE,
)
QUESTION_CUE_RE = re.compile(r"(\?|？|什么|多少|哪里|怎么|如何|是否|是谁|what|how|where|when|who|which)", re.IGNORECASE)
BINARY_URL_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|avif|svg|mp4|mov|webm|mp3|wav|flac|ogg|zip|rar|7z|tar|gz|exe|dmg)(?:$|[?#])",
    re.IGNORECASE,
)


@dataclass
class WebSource:
    kind: str
    title: str
    url: str
    snippet: str = ""


@dataclass
class WebContext:
    pages: list[WebSource] = field(default_factory=list)
    search_results: list[WebSource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def has_content(self) -> bool:
        return bool(self.pages or self.search_results or self.errors)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.description = ""
        self.body_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta" and not self.description:
            key = (attrs_map.get("name") or attrs_map.get("property") or "").lower()
            if key in {"description", "og:description", "twitter:description"}:
                self.description = _normalize_whitespace(attrs_map.get("content", ""))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = _normalize_whitespace(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif self._skip_depth == 0:
            self.body_parts.append(text)

    @property
    def title(self) -> str:
        return _normalize_whitespace(" ".join(self.title_parts))

    @property
    def body(self) -> str:
        return _normalize_whitespace(" ".join(self.body_parts))


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebSource] = []
        self._capturing_title = False
        self._current_href = ""
        self._current_title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        css_class = attrs_map.get("class", "")
        if "result__a" not in css_class and "result-link" not in css_class:
            return
        href = attrs_map.get("href", "")
        if not href:
            return
        self._capturing_title = True
        self._current_href = _clean_duckduckgo_url(href)
        self._current_title = []

    def handle_data(self, data: str) -> None:
        if self._capturing_title:
            text = _normalize_whitespace(data)
            if text:
                self._current_title.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capturing_title:
            return
        title = _normalize_whitespace(" ".join(self._current_title))
        if title and self._current_href and not any(item.url == self._current_href for item in self.results):
            self.results.append(WebSource(kind="search", title=title, url=self._current_href))
        self._capturing_title = False
        self._current_href = ""
        self._current_title = []


class WebContextService:
    def __init__(self, env: EnvSettings) -> None:
        self.env = env
        self.user_agent = "DC_Bot/0.1 (+https://github.com/)"

    async def build_context_messages(
        self,
        prompt: str,
        *,
        settings: object,
        extra_text: str = "",
    ) -> list[dict[str, str]]:
        if not bool(getattr(settings, "ai_web_tools_enabled", True)):
            return []

        context = await self.build_context(
            "\n".join(part for part in [prompt, extra_text] if part),
            fetch_enabled=bool(getattr(settings, "ai_web_fetch_enabled", True)),
            search_enabled=bool(getattr(settings, "ai_web_search_enabled", True)),
            fetch_limit=int(getattr(settings, "ai_web_fetch_limit", 3) or 3),
            search_result_limit=int(getattr(settings, "ai_web_search_result_limit", 4) or 4),
            fetch_max_bytes=int(getattr(settings, "ai_web_fetch_max_bytes", 262144) or 262144),
            fetch_snippet_chars=int(getattr(settings, "ai_web_fetch_snippet_chars", 1400) or 1400),
        )
        if not context.has_content():
            return []
        context_char_limit = int(getattr(settings, "ai_web_context_char_limit", 4500) or 4500)
        return [{"role": "system", "content": self.format_context(context, char_limit=context_char_limit)}]

    async def build_context(
        self,
        prompt: str,
        *,
        fetch_enabled: bool,
        search_enabled: bool,
        fetch_limit: int,
        search_result_limit: int,
        fetch_max_bytes: int,
        fetch_snippet_chars: int,
    ) -> WebContext:
        context = WebContext()
        urls = self.extract_urls(prompt)
        tasks: list[asyncio.Task[WebSource | str | None]] = []

        fetch_limit = max(0, min(fetch_limit, 5))
        search_result_limit = max(1, min(search_result_limit, 8))
        fetch_max_bytes = max(16384, min(fetch_max_bytes, 1048576))
        fetch_snippet_chars = max(300, min(fetch_snippet_chars, 5000))

        if fetch_enabled:
            for url in urls[:fetch_limit]:
                if self._should_fetch_url(url):
                    tasks.append(
                        asyncio.create_task(
                            self.fetch_page(
                                url,
                                max_bytes=fetch_max_bytes,
                                snippet_chars=fetch_snippet_chars,
                            )
                        )
                    )

        search_query = self.extract_search_query(prompt)
        if search_enabled and search_query:
            tasks.append(asyncio.create_task(self.search(search_query, limit=search_result_limit)))

        if not tasks:
            return context

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, WebSource):
                context.pages.append(result)
            elif isinstance(result, list):
                context.search_results.extend(item for item in result if isinstance(item, WebSource))
            elif isinstance(result, Exception):
                context.errors.append(self._describe_exception(result))
            elif isinstance(result, str):
                context.errors.append(result)

        return context

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        urls: list[str] = []
        for match in URL_RE.findall(text or ""):
            url = match.rstrip(TRAILING_URL_PUNCTUATION)
            if url and url not in urls:
                urls.append(url)
        return urls

    @staticmethod
    def extract_search_query(text: str) -> str:
        cleaned = _normalize_whitespace(URL_RE.sub(" ", text or ""))
        if not cleaned:
            return ""
        explicit = SEARCH_PREFIX_RE.search(cleaned)
        if explicit:
            return _truncate(_normalize_whitespace(explicit.group(1)), 180)
        if SEARCH_CUE_RE.search(cleaned) and QUESTION_CUE_RE.search(cleaned):
            return _truncate(cleaned, 180)
        return ""

    async def fetch_page(
        self,
        url: str,
        *,
        max_bytes: int = 262144,
        snippet_chars: int = 1400,
    ) -> WebSource | str | None:
        allowed_error = self._validate_public_url(url)
        if allowed_error:
            return allowed_error
        resolved_error = await self._validate_resolved_public_host(url)
        if resolved_error:
            return resolved_error
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.2",
        }
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=headers) as client:
                async with client.stream("GET", url) as response:
                    if response.is_error:
                        return f"抓取网页失败：{url} (HTTP {response.status_code})"

                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not any(token in content_type for token in ("html", "text", "xml", "json")):
                        return f"跳过非文本网页：{url} ({content_type.split(';', 1)[0]})"

                    body = bytearray()
                    truncated = False
                    async for chunk in response.aiter_bytes():
                        remaining = max_bytes - len(body)
                        if remaining <= 0:
                            truncated = True
                            break
                        if len(chunk) > remaining:
                            body.extend(chunk[:remaining])
                            truncated = True
                            break
                        body.extend(chunk)
                    text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                    final_url = str(response.url)
        except httpx.TimeoutException:
            return f"抓取网页超时：{url}"
        except httpx.RequestError as exc:
            return f"抓取网页失败：{url} ({exc.__class__.__name__})"

        if "json" in content_type:
            snippet = _truncate(_normalize_whitespace(text), snippet_chars)
            title = final_url
        else:
            extractor = _HTMLTextExtractor()
            try:
                extractor.feed(text)
            except Exception:
                LOGGER.debug("HTML parsing failed for %s", final_url, exc_info=True)
            title = extractor.title or final_url
            snippet_parts = [extractor.description, extractor.body]
            snippet = _truncate(_normalize_whitespace(" ".join(part for part in snippet_parts if part)), snippet_chars)
        if not snippet:
            return f"抓取网页成功但没有可读正文：{final_url}"
        if truncated:
            snippet = _truncate(f"{snippet} [网页内容超过下载上限，已截断。]", snippet_chars)
        return WebSource(kind="fetch", title=_truncate(title, 160), url=final_url, snippet=snippet)

    async def search(self, query: str, *, limit: int) -> list[WebSource] | str:
        provider = (self.env.ai_web_search_provider or "duckduckgo").strip().lower()
        if provider == "brave":
            return await self._search_brave(query, limit=limit)
        if provider == "serper":
            return await self._search_serper(query, limit=limit)
        return await self._search_duckduckgo(query, limit=limit)

    async def _search_brave(self, query: str, *, limit: int) -> list[WebSource] | str:
        api_key = self.env.brave_search_api_key or self.env.ai_web_search_api_key
        if not api_key:
            return "Brave Search 未配置 BRAVE_SEARCH_API_KEY。"
        base_url = self.env.ai_web_search_base_url or "https://api.search.brave.com/res/v1/web/search"
        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
        params = {"q": query, "count": max(1, min(limit, 10))}
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                response = await client.get(base_url, params=params)
        except httpx.RequestError as exc:
            return f"Brave Search 请求失败：{exc.__class__.__name__}"
        if response.is_error:
            return f"Brave Search 请求失败：HTTP {response.status_code}"
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return "Brave Search 返回了非 JSON 内容。"
        items = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
        return [
            WebSource(
                kind="search",
                title=_clean_text(str(item.get("title", ""))) or str(item.get("url", "")),
                url=str(item.get("url", "")),
                snippet=_clean_text(str(item.get("description", ""))),
            )
            for item in items[:limit]
            if isinstance(item, dict) and item.get("url")
        ]

    async def _search_serper(self, query: str, *, limit: int) -> list[WebSource] | str:
        api_key = self.env.serper_api_key or self.env.ai_web_search_api_key
        if not api_key:
            return "Serper Search 未配置 SERPER_API_KEY。"
        base_url = self.env.ai_web_search_base_url or "https://google.serper.dev/search"
        headers = {"Content-Type": "application/json", "X-API-KEY": api_key}
        payload = {"q": query, "num": max(1, min(limit, 10))}
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers) as client:
                response = await client.post(base_url, json=payload)
        except httpx.RequestError as exc:
            return f"Serper Search 请求失败：{exc.__class__.__name__}"
        if response.is_error:
            return f"Serper Search 请求失败：HTTP {response.status_code}"
        try:
            data = response.json()
        except json.JSONDecodeError:
            return "Serper Search 返回了非 JSON 内容。"
        items = data.get("organic", []) if isinstance(data, dict) else []
        return [
            WebSource(
                kind="search",
                title=_clean_text(str(item.get("title", ""))) or str(item.get("link", "")),
                url=str(item.get("link", "")),
                snippet=_clean_text(str(item.get("snippet", ""))),
            )
            for item in items[:limit]
            if isinstance(item, dict) and item.get("link")
        ]

    async def _search_duckduckgo(self, query: str, *, limit: int) -> list[WebSource] | str:
        url = self.env.ai_web_search_base_url or "https://duckduckgo.com/html/"
        headers = {"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"}
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True) as client:
                response = await client.get(url, params={"q": query})
        except httpx.RequestError as exc:
            return f"DuckDuckGo 搜索失败：{exc.__class__.__name__}"
        if response.is_error:
            return f"DuckDuckGo 搜索失败：HTTP {response.status_code}"
        parser = _DuckDuckGoParser()
        try:
            parser.feed(response.text)
        except Exception:
            LOGGER.debug("DuckDuckGo result parsing failed", exc_info=True)
        results = parser.results[:limit]
        if results:
            return results
        fallback_url = f"https://duckduckgo.com/?q={quote_plus(query)}"
        return [WebSource(kind="search", title=f"DuckDuckGo 搜索：{query}", url=fallback_url)]

    def format_context(self, context: WebContext, *, char_limit: int = 4500) -> str:
        char_limit = max(1000, min(char_limit, 20000))
        lines = [
            "以下是系统在回答前自动获取的网页/搜索上下文。只在它和用户问题相关时使用；涉及事实或时效信息时，请引用对应标题或 URL；不要编造来源。"
        ]
        if context.pages:
            lines.append("\n[自动抓取网页]")
            for index, source in enumerate(context.pages, start=1):
                if not self._append_with_budget(lines, self._format_source(f"F{index}", source), char_limit):
                    return "\n".join(lines).strip()
        if context.search_results:
            lines.append("\n[自动搜索结果]")
            for index, source in enumerate(context.search_results, start=1):
                if not self._append_with_budget(lines, self._format_source(f"S{index}", source), char_limit):
                    return "\n".join(lines).strip()
        if context.errors:
            lines.append("\n[工具提示]")
            for error in context.errors[:3]:
                if not self._append_with_budget(lines, f"- {error}", char_limit):
                    return "\n".join(lines).strip()
        return "\n".join(lines).strip()

    @staticmethod
    def _append_with_budget(lines: list[str], text: str, char_limit: int) -> bool:
        current_length = len("\n".join(lines))
        remaining = char_limit - current_length - 1
        if remaining <= 0:
            return False
        if len(text) <= remaining:
            lines.append(text)
            return True
        if remaining > 80:
            lines.append(_truncate(text, remaining))
        return False

    @staticmethod
    def _format_source(label: str, source: WebSource) -> str:
        snippet = _truncate(source.snippet, 900) if source.snippet else ""
        parts = [f"[{label}] {source.title}", f"URL: {source.url}"]
        if snippet:
            parts.append(f"摘要: {snippet}")
        return "\n".join(parts)

    @staticmethod
    def _should_fetch_url(url: str) -> bool:
        return not BINARY_URL_RE.search(url)

    @staticmethod
    def _validate_public_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return f"跳过非 HTTP URL：{url}"
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return f"跳过无效 URL：{url}"
        if host in {"localhost"} or host.endswith(".local"):
            return f"跳过本地地址：{url}"
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return ""
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
            return f"跳过内网地址：{url}"
        return ""

    @staticmethod
    async def _validate_resolved_public_host(url: str) -> str:
        host = urlparse(url).hostname
        if not host:
            return f"跳过无效 URL：{url}"
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return f"无法解析网页域名：{url}"
        for info in infos:
            address_text = info[4][0]
            try:
                address = ipaddress.ip_address(address_text)
            except ValueError:
                continue
            if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
                return f"跳过解析到内网地址的 URL：{url}"
        return ""

    @staticmethod
    def _describe_exception(exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__


def _clean_duckduckgo_url(href: str) -> str:
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg:
        return unquote(uddg[0])
    return href


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return _normalize_whitespace(text)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"
