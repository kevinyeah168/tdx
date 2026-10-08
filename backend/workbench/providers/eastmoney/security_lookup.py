from __future__ import annotations

import re
import time

from workbench.providers.tdx.symbols import infer_market_label_for_code, normalize_code

_EM_SYMBOL = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
_SUGGEST_API = "https://searchapi.eastmoney.com/api/suggest/get"
_SUGGEST_TOKEN = "D43BF722C8E277BFC906FB18D015EA32"


def normalize_em_symbol(symbol: str) -> tuple[str, str]:
    """Correct East Money sc values such as SZ920252 -> BJ920252."""
    normalized = symbol.strip().upper()
    match = _EM_SYMBOL.fullmatch(normalized)
    if match is None:
        code = normalized
        if len(code) > 2 and code[:2] in {"SH", "SZ", "BJ"}:
            code = code[2:]
    else:
        code = match.group(2)
    code = normalize_code(code)
    prefix = infer_market_label_for_code(code)
    return f"{prefix}{code}", code


def fetch_security_names_by_codes(codes: list[str]) -> dict[str, str]:
    if not codes:
        return {}
    unique = list(dict.fromkeys(code.strip() for code in codes if code.strip()))
    resolved: dict[str, str] = {}
    for code in unique:
        name = _fetch_suggest_name(code)
        if name:
            resolved[code] = name
    return resolved


def _fetch_suggest_name(code: str) -> str | None:
    try:
        from curl_cffi import requests
    except ImportError:
        return None

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = requests.get(
                _SUGGEST_API,
                params={
                    "input": code,
                    "type": "14",
                    "token": _SUGGEST_TOKEN,
                    "count": "5",
                },
                impersonate="chrome",
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            rows = (payload.get("QuotationCodeTable") or {}).get("Data") or []
            if not isinstance(rows, list):
                return None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("Code") or "").strip() == code:
                    name = str(row.get("Name") or "").strip()
                    return name or None
            return None
        except Exception as exc:
            last_error = exc
            if attempt < 1:
                time.sleep(0.2)
    if last_error is not None:
        return None
    return None
