"""联网检索与抓取：关键词搜索（DuckDuckGo HTML）或按 URL 获取页面文本摘要。"""

import html as html_lib
import ipaddress
import json
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory

_USER_AGENT = "Mozilla/5.0 (compatible; LoomMind/1.0; +https://github.com/) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_FETCH_TIMEOUT_SEC = 25
_SEARCH_TIMEOUT_SEC = 25
_MAX_FETCH_BYTES = 512 * 1024
_MAX_OUTPUT_CHARS = 24_000
_MAX_SEARCH_RESULTS = 12


def _truncate(text: str, max_chars: int = _MAX_OUTPUT_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 20] + "\n…（输出已截断）\n"


def _host_ips(hostname: str) -> list[str]:
    ips: list[str] = []
    for fam, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
        if fam == socket.AF_INET:
            ips.append(sockaddr[0])
        elif fam == socket.AF_INET6:
            ips.append(sockaddr[0])
    return ips


def _ip_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved)


def _validate_public_http_url(url: str) -> tuple[str | None, str | None]:
    raw = (url or "").strip()
    if not raw:
        return None, "URL 为空"
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None, "仅支持 http/https URL"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None, "缺少主机名"
    if host == "localhost" or host.endswith(".localhost"):
        return None, "禁止访问 localhost"
    try:
        for ip in _host_ips(host):
            if _ip_blocked(ip):
                return None, f"禁止访问内网/保留地址: {ip}"
    except OSError as ex:
        return None, f"DNS 解析失败: {ex}"
    norm = urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return norm, None


def _http_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[int, str, bytes]:
    hdrs = {"User-Agent": _USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
        status = getattr(resp, "status", 200) or 200
        ctype = resp.headers.get("Content-Type", "") or ""
        body = resp.read(_MAX_FETCH_BYTES + 1)
    if len(body) > _MAX_FETCH_BYTES:
        body = body[:_MAX_FETCH_BYTES]
    return status, ctype, body


def _html_to_text(html: str) -> str:
    class _Strip(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._chunks: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
            t = tag.lower()
            if t in ("script", "style", "noscript"):
                self._skip += 1

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in ("script", "style", "noscript") and self._skip > 0:
                self._skip -= 1
            elif t in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "title"):
                self._chunks.append("\n")

        def handle_data(self, data: str) -> None:
            if self._skip > 0:
                return
            if data:
                self._chunks.append(data)

        def text(self) -> str:
            raw = "".join(self._chunks)
            raw = html_lib.unescape(raw)
            raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
            raw = re.sub(r"\n{3,}", "\n\n", raw)
            return raw.strip()

    p = _Strip()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    return p.text()


def _duckduckgo_resolve_href(href: str) -> str | None:
    h = (href or "").strip()
    if not h:
        return None
    if h.startswith("//"):
        h = "https:" + h
    parsed = urllib.parse.urlparse(h)
    if "duckduckgo.com" in (parsed.netloc or "").lower() and parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            return urllib.parse.unquote(uddg)
    if parsed.scheme in ("http", "https") and "duckduckgo.com" not in (parsed.netloc or "").lower():
        return urllib.parse.urlunparse(parsed)
    return None


def _parse_ddg_html_result_snippets(page_html: str) -> list[tuple[str, str, str]]:
    """返回 (title, url, snippet) 列表。"""
    out: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href = html_lib.unescape(m.group(1).strip())
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = html_lib.unescape(re.sub(r"\s+", " ", title).strip())
        real = _duckduckgo_resolve_href(href)
        if not real or not title:
            continue
        out.append((title, real, ""))

    if not out:
        return []

    snippets = [""] * len(out)
    snippet_iter = list(
        re.finditer(
            r'class="result__snippet"[^>]*>(.*?)</',
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    for i, sn in enumerate(snippet_iter):
        if i >= len(out):
            break
        raw_sn = re.sub(r"<[^>]+>", "", sn.group(1))
        snippets[i] = html_lib.unescape(re.sub(r"\s+", " ", raw_sn).strip())

    return [(out[i][0], out[i][1], snippets[i]) for i in range(len(out))]


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def web_search(query: str, max_results: int = 8) -> str:
        """在互联网上搜索关键词，返回若干条标题、链接与摘要（DuckDuckGo）。

        当用户问题需要最新资料、事实核对或你不知道答案时调用。
        参数 query：搜索关键词（自然语言或关键字）。
        参数 max_results：返回条数上限（1–12），默认 8。
        """
        q = (query or "").strip()
        if not q:
            return "web_search 失败：query 为空"
        lim = max(1, min(int(max_results), _MAX_SEARCH_RESULTS))

        # 先试 JSON API：Instant Answer + RelatedTopics（无广告 HTML 结构更稳）
        try:
            enc = urllib.parse.quote(q, safe="")
            api_url = f"https://api.duckduckgo.com/?q={enc}&format=json&no_html=1&skip_disambig=1"
            status, _ctype, body = _http_request(api_url, timeout=_SEARCH_TIMEOUT_SEC)
        except urllib.error.HTTPError as ex:
            return f"web_search 失败：HTTP {ex.code}"
        except urllib.error.URLError as ex:
            return f"web_search 失败：网络错误：{ex.reason}"
        except TimeoutError:
            return "web_search 失败：请求超时"
        except OSError as ex:
            return f"web_search 失败：{ex}"

        if status != 200:
            return f"web_search 失败：HTTP {status}"

        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            data = {}

        lines: list[str] = []
        heading = data.get("Heading")
        abstract = data.get("AbstractText")
        abs_url = data.get("AbstractURL")
        if heading or abstract:
            lines.append("## Instant answer")
            if heading:
                lines.append(f"- Title: {heading}")
            if abstract:
                lines.append(f"- Summary: {abstract}")
            if abs_url:
                lines.append(f"- URL: {abs_url}")

        def walk_related(obj, depth: int = 0) -> None:
            if depth > 6 or len(lines) > 200:
                return
            if isinstance(obj, dict):
                text = obj.get("Text")
                url = obj.get("FirstURL")
                if isinstance(text, str) and text.strip():
                    entry = f"- {text.strip()}"
                    if isinstance(url, str) and url.strip():
                        entry += f" | {url.strip()}"
                    lines.append(entry)
                for v in obj.values():
                    walk_related(v, depth + 1)
            elif isinstance(obj, list):
                for it in obj:
                    walk_related(it, depth + 1)

        rel = data.get("RelatedTopics")
        if rel:
            lines.append("\n## Related")
            walk_related(rel)

        # 若无较完整 Instant Answer，再抓 HTML 结果页补全链接列表
        abs_text = abstract if isinstance(abstract, str) else ""
        need_html = not abs_text.strip() or len(abs_text.strip()) < 80
        html_hits: list[tuple[str, str, str]] = []
        if need_html:
            try:
                post = urllib.parse.urlencode({"q": q}).encode("utf-8")
                status_h, _ct, body_h = _http_request(
                    "https://html.duckduckgo.com/html/",
                    data=post,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": "https://duckduckgo.com/",
                    },
                    timeout=_SEARCH_TIMEOUT_SEC,
                )
                if status_h == 200:
                    page = body_h.decode("utf-8", errors="replace")
                    html_hits = _parse_ddg_html_result_snippets(page)
            except Exception:
                pass

        if html_hits:
            lines.append("\n## Web results")
            for title, url, snip in html_hits[:lim]:
                block = f"- **{title}**\n  - URL: {url}"
                if snip:
                    block += f"\n  - Snippet: {snip}"
                lines.append(block)

        if not lines:
            return "web_search：未解析到结果（可能被站点拒绝或查询无命中）。可换关键词或改用 web_fetch 直接打开已知 URL。"

        return _truncate("\n".join(lines))

    @mcp.tool()
    def web_fetch(url: str, max_chars: int = 12000) -> str:
        """通过 HTTP(S) 获取给定 URL 的正文文本摘要（HTML 会剥离标签）。

        当用户消息里出现需要打开的链接、或 web_search 返回的 URL 需要阅读原文时使用。
        参数 url：以 http:// 或 https:// 开头的完整 URL。
        参数 max_chars：返回的最大字符数（避免过长），默认 12000。
        """
        norm, err = _validate_public_http_url(url)
        if norm is None:
            return f"web_fetch 失败：{err}"
        cap = max(500, min(int(max_chars), _MAX_OUTPUT_CHARS))

        try:
            status, ctype, body = _http_request(norm, timeout=_FETCH_TIMEOUT_SEC)
        except urllib.error.HTTPError as ex:
            return f"web_fetch 失败：HTTP {ex.code}"
        except urllib.error.URLError as ex:
            return f"web_fetch 失败：网络错误：{ex.reason}"
        except TimeoutError:
            return "web_fetch 失败：请求超时"
        except OSError as ex:
            return f"web_fetch 失败：{ex}"

        if status != 200:
            return f"web_fetch 失败：HTTP {status}"

        text = body.decode("utf-8", errors="replace")
        ct_lower = (ctype or "").lower()
        if "html" in ct_lower:
            text = _html_to_text(text)
        else:
            text = text.strip()

        header = f"URL: {norm}\nContent-Type: {ctype or '(unknown)'}\nHTTP: {status}\n\n"
        return _truncate(header + text, max_chars=cap)

    return {
        "web_search": TrustCategory.NETWORK,
        "web_fetch": TrustCategory.NETWORK,
    }
