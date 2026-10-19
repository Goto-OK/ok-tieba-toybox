"""HTTP 抓取层：Cookie、重试、限速、本地缓存、反爬识别。

只依赖标准库，避免额外安装 requests；解析层需要 lxml，导出层需要 openpyxl。
"""

from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CAPTCHA_MARKERS = (
    "百度安全验证",
    "百度安全",
    "wappass.baidu.com",
    "bioc-static",
    "radar-init-script",
    "请完成安全验证",
    "security-verify",
)

NOT_FOUND_MARKERS = (
    "抱歉，您访问的贴子可能已被删除",
    "该贴已被删除",
    "帖子已被删除",
    "您访问的页面不存在",
    "该吧尚未建立",
)


class FetchError(RuntimeError):
    """网络层错误（重试后仍失败）。"""


class CaptchaError(FetchError):
    """被百度安全验证拦截。"""


class ThreadGoneError(FetchError):
    """帖子不存在 / 已删除。"""


@dataclass
class Response:
    text: str
    url: str
    status: int

    def looks_like_captcha(self) -> bool:
        if self.status in (403, 412):
            return True
        # 正常楼层页里也可能出现 passport/bioc 字样，只有确实没有楼层结构时才判定为验证页
        if "l_post" in self.text or "post_content_" in self.text:
            return False
        sample = self.text[:6000]
        return any(marker in sample for marker in CAPTCHA_MARKERS)


def parse_cookie_input(raw: str) -> Dict[str, str]:
    """把浏览器里复制的 Cookie 串或 JSON 对象解析成 dict。"""
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    cookies: Dict[str, str] = {}
    for part in re.split(r"[;\n\r]+", raw):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip().strip('"')
    return cookies


def load_cookie_file(path: str) -> Dict[str, str]:
    """读取 Cookie：支持「k=v; k2=v2」文本，也支持 Netscape cookies.txt。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        content = handle.read()
    lines = [line for line in content.splitlines() if line.strip()]
    netscape = any(len(line.split("\t")) >= 7 and not line.startswith("#") for line in lines)
    if not netscape:
        return parse_cookie_input(content)

    cookies: Dict[str, str] = {}
    for line in lines:
        if line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, _flag, path, _secure, _expires, name, value = fields[:7]
        if "baidu" not in domain:
            continue
        cookies[name] = value
    return cookies


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", name)
    return cleaned.strip("_") or "page"


def _decompress(body: bytes, headers) -> bytes:
    """urllib 不会自动解压，这里按 Content-Encoding 处理 gzip / deflate。"""
    encoding = ""
    try:
        encoding = (headers.get("Content-Encoding") or "").lower().strip()
    except AttributeError:
        encoding = ""
    if not body:
        return body
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        if encoding == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -15)
    except (OSError, zlib.error):
        return body
    return body


class Fetcher:
    """带 Cookie、限速、缓存与重试的抓取器。"""

    DEFAULT_PROXY: Optional[str] = None

    def __init__(
        self,
        cookie: Optional[Dict[str, str]] = None,
        user_agent: str = DEFAULT_UA,
        timeout: float = 20.0,
        retries: int = 3,
        delay: float = 0.8,
        proxy: Optional[str] = None,
        cache_dir: Optional[str] = None,
        dump_dir: Optional[str] = None,
        refresh: bool = False,
        verbose: bool = True,
    ) -> None:
        if proxy is None:
            proxy = Fetcher.DEFAULT_PROXY
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = max(1, retries)
        self.delay = max(0.0, delay)
        self.cache_dir = cache_dir
        self.dump_dir = dump_dir
        self.refresh = refresh
        self.verbose = verbose
        self.online = True
        self._dump_counter = 0

        self.jar = http.cookiejar.CookieJar()
        for name, value in (cookie or {}).items():
            self._add_cookie(name, value)

        self.opener = self._build_opener(proxy)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        if dump_dir:
            os.makedirs(dump_dir, exist_ok=True)

    # ------------------------------------------------------------------ HTTP
    def _build_opener(self, proxy: Optional[str]) -> urllib.request.OpenerDirector:
        handlers = [
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPRedirectHandler(),
        ]
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        context = ssl.create_default_context()
        handlers.append(urllib.request.HTTPSHandler(context=context))
        return urllib.request.build_opener(*handlers)

    def add_cookies(self, cookies: Dict[str, str]) -> None:
        for name, value in cookies.items():
            self._add_cookie(name, value)

    def _add_cookie(self, name: str, value: str) -> None:
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=".baidu.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=False,
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        self.jar.set_cookie(cookie)

    def _headers(self, url: str) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(url)
        if "/p/comment" in parsed.path:
            query = urllib.parse.parse_qs(parsed.query)
            tid = (query.get("tid") or [""])[0]
            referer = f"https://tieba.baidu.com/p/{tid}" if tid else "https://tieba.baidu.com/"
        else:
            referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else "https://tieba.baidu.com/"
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Referer": referer,
            "Connection": "keep-alive",
        }

    def _fetch_bytes(
        self, url: str, headers: Dict[str, str], data: Optional[bytes] = None
    ) -> Tuple[bytes, int, Dict[str, str]]:
        """单次请求；测试时可以覆盖此方法。"""
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
                return _decompress(body, response.headers), response.status, dict(response.headers)
        except urllib.error.HTTPError as error:
            body = error.read() if error.fp else b""
            return _decompress(body, error.headers), error.code, dict(error.headers or {})
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as error:
            raise FetchError(str(error)) from error

    def _sleep(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay + random.uniform(0, self.delay * 0.35))

    # ------------------------------------------------------------------ cache
    def _cache_path(self, url: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        return os.path.join(self.cache_dir, f"{digest}.html")

    def _read_cache(self, url: str) -> Optional[str]:
        path = self._cache_path(url)
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        return None

    def _write_cache(self, url: str, text: str) -> None:
        path = self._cache_path(url)
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)

    def _dump(self, name: Optional[str], url: str, text: str) -> None:
        if not self.dump_dir:
            return
        self._dump_counter += 1
        label = _safe_filename(name or f"page_{self._dump_counter}")
        path = os.path.join(self.dump_dir, f"{self._dump_counter:03d}_{label}.html")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if self.verbose:
            print(f"    [dump] {path}")

    # ------------------------------------------------------------------ public
    def get(self, url: str, name: Optional[str] = None, expect_json: bool = False) -> Response:
        cached = None if self.refresh else self._read_cache(url)
        if cached is not None:
            return Response(cached, url, 200)

        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            self._sleep()
            try:
                body, status, headers = self._fetch_bytes(url, self._headers(url))
            except FetchError as error:
                last_error = error
                if self.verbose:
                    print(f"    [retry {attempt}/{self.retries}] {error}")
                time.sleep(min(2**attempt, 8))
                continue

            text = self._decode(body, headers)
            response = Response(text, url, status)

            if status in (403, 412) or response.looks_like_captcha():
                raise CaptchaError(
                    "请求被百度安全验证拦截（当前网络 IP 可能被判定为异常）。"
                    '请用浏览器打开该帖子，登录后复制 Cookie 再重试：--cookie "你的Cookie"。'
                )
            if status == 404:
                raise ThreadGoneError(f"页面不存在（HTTP 404）：{url}")
            if status >= 500:
                last_error = FetchError(f"HTTP {status}")
                if self.verbose:
                    print(f"    [retry {attempt}/{self.retries}] HTTP {status}")
                time.sleep(min(2**attempt, 8))
                continue
            if status >= 400:
                raise FetchError(f"HTTP {status}：{url}")

            if not expect_json:
                hit = next((m for m in NOT_FOUND_MARKERS if m in text), None)
                if hit:
                    raise ThreadGoneError(f"帖子不可访问：{hit}")

            self._write_cache(url, text)
            self._dump(name, url, text)
            return response

        raise FetchError(f"重试 {self.retries} 次仍失败：{url}（{last_error}）")

    def get_json(self, url: str, name: Optional[str] = None) -> dict:
        response = self.get(url, name=name, expect_json=True)
        text = response.text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 有些接口返回 JSONP：callback({...})
            match = re.search(r"^\s*[\w$.]+\s*\(\s*(\{.*\})\s*\)\s*;?\s*$", text, re.S)
            if match:
                return json.loads(match.group(1))
            raise FetchError(f"接口返回的不是 JSON：{text[:120]}")

    def post_form(self, url: str, data: Dict, name: Optional[str] = None) -> Response:
        """提交表单（贴吧客户端接口用），带重试与验证码识别。"""
        body = urllib.parse.urlencode(data).encode()
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            self._sleep()
            headers = self._headers(url)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            try:
                raw, status, resp_headers = self._fetch_bytes(url, headers, body)
            except FetchError as error:
                last_error = error
                time.sleep(min(2**attempt, 8))
                continue
            response = Response(self._decode(raw, resp_headers), url, status)
            if status in (403, 412) or response.looks_like_captcha():
                raise CaptchaError("请求被百度安全验证拦截，请更新 Cookie 后重试。")
            if status >= 500:
                last_error = FetchError(f"HTTP {status}")
                time.sleep(min(2**attempt, 8))
                continue
            if status >= 400:
                raise FetchError(f"HTTP {status}：{url}")
            self._dump(name, url, response.text)
            return response
        raise FetchError(f"重试 {self.retries} 次仍失败：{url}（{last_error}）")

    def post_json(self, url: str, data: Dict, name: Optional[str] = None) -> dict:
        response = self.post_form(url, data, name=name)
        return json.loads(response.text)

    @staticmethod
    def _decode(body: bytes, headers: Dict[str, str]) -> str:
        encoding = ""
        content_type = headers.get("Content-Type", "") or headers.get("content-type", "")
        match = re.search(r"charset=([\w-]+)", content_type, re.I)
        if match:
            encoding = match.group(1)
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        for candidate in (encoding, "utf-8", "gb18030"):
            if not candidate:
                continue
            try:
                return body.decode(candidate)
            except (LookupError, UnicodeDecodeError):
                continue
        return body.decode("utf-8", errors="replace")

    def close(self) -> None:
        pass

    def cookie_dict(self) -> Dict[str, str]:
        """返回当前 Cookie 的 {name: value} 副本（给需要表单签名的接口用）。"""
        return {cookie.name: cookie.value or "" for cookie in self.jar}
