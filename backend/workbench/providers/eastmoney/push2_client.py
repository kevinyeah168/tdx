"""East Money push2 clist client with browser-like session cookies."""

from __future__ import annotations

import json
import random
import re
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

JSONP_RE = re.compile(r"^[^(]+\((\{.*\})\);?\s*$", re.DOTALL)

_session_lock = threading.Lock()
_session_cookie: str | None = None
_session_expires_at = 0.0
_SESSION_TTL_SECONDS = 300.0


def gen_visitor_cookie() -> str:
    def hex32() -> str:
        return "".join(random.choice("0123456789abcdef") for _ in range(32))

    def num14() -> str:
        return "".join(random.choice("0123456789") for _ in range(14))

    def rand_alnum(length: int) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(random.choice(alphabet) for _ in range(length))

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st_sp = now.replace(" ", "%20").replace(":", "%3A")
    ts = time.strftime("%Y%m%d%H%M%S") + f"{random.randint(10, 99):02d}"
    return "; ".join(
        [
            f"qgqp_b_id={hex32()}",
            f"st_pvi={num14()}",
            f"st_si={num14()}",
            f"st_sp={st_sp}",
            "st_inirUrl=",
            "st_sn=1",
            f"st_psi={ts}-{random.randint(10**11, 10**12 - 1)}-{random.randint(10**9, 10**10 - 1)}",
            "st_asi=delete",
            f"st_nvi={rand_alnum(22)}",
            f"nid18={hex32()}",
            f"nid18_create_time={int(time.time() * 1000)}",
        ]
    )


def visitor_cookie() -> str:
    global _session_cookie, _session_expires_at
    now = time.monotonic()
    with _session_lock:
        if _session_cookie and now < _session_expires_at:
            return _session_cookie
        _session_cookie = gen_visitor_cookie()
        _session_expires_at = now + _SESSION_TTL_SECONDS
        return _session_cookie


def reset_visitor_cookie() -> None:
    global _session_cookie, _session_expires_at
    with _session_lock:
        _session_cookie = None
        _session_expires_at = 0.0


def build_push2_headers(
    *,
    referer: str = "https://quote.eastmoney.com/center/gridlist.html",
    cookie: str | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Origin": "https://quote.eastmoney.com",
        "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-dest": "script",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def append_jsonp_params(params: dict[str, str]) -> dict[str, str]:
    enriched = dict(params)
    enriched.setdefault("cb", f"jQuery3510{random.randint(10**18, 10**19 - 1)}_{int(time.time() * 1000)}")
    enriched["_"] = str(int(time.time() * 1000))
    return enriched


def parse_push2_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("eastmoney push2 response is empty")
    if stripped.startswith("{"):
        payload = json.loads(stripped)
    else:
        match = JSONP_RE.match(stripped)
        if not match:
            raise RuntimeError("eastmoney push2 response is not JSON or JSONP")
        payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise RuntimeError("eastmoney push2 response is not a JSON object")
    return payload


def _http_get_push2_urllib(
    url: str,
    *,
    params: dict[str, str],
    referer: str,
    cookie: str,
    timeout: float,
) -> str:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    request = urllib.request.Request(
        full_url,
        headers=build_push2_headers(referer=referer, cookie=cookie),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def http_get_push2(
    url: str,
    *,
    params: dict[str, str],
    referer: str = "https://quote.eastmoney.com/center/gridlist.html",
    timeout: float = 10,
) -> dict[str, Any]:
    enriched = append_jsonp_params(params)
    cookie = visitor_cookie()
    headers = build_push2_headers(referer=referer, cookie=cookie)
    text: str | None = None
    try:
        from curl_cffi import requests

        response = requests.get(
            url,
            params=enriched,
            headers=headers,
            timeout=timeout,
            impersonate="chrome",
        )
        if response.status_code != 200:
            raise RuntimeError(f"eastmoney push2 failed with status {response.status_code}")
        text = response.text
    except Exception:
        try:
            text = _http_get_push2_urllib(
                url,
                params=enriched,
                referer=referer,
                cookie=cookie,
                timeout=timeout,
            )
        except urllib.error.URLError as urllib_error:
            raise RuntimeError(f"eastmoney push2 urllib failed: {urllib_error}") from urllib_error
    if text is None:
        raise RuntimeError("eastmoney push2 response is empty")
    return parse_push2_payload(text)
