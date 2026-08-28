from __future__ import annotations

import re

from easy_tdx import Market


_A_SHARE_PREFIXES = {
    Market.SH: ("600", "601", "603", "605", "688"),
    Market.SZ: ("000", "001", "002", "003", "300", "301"),
    Market.BJ: ("920", "430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879"),
}

_MARKET_LABELS = {
    Market.SH: "SH",
    Market.SZ: "SZ",
    Market.BJ: "BJ",
}


def market_label(market: Market | str) -> str:
    if isinstance(market, Market):
        return _MARKET_LABELS[market]
    normalized = str(market).strip().upper()
    if normalized not in {"SH", "SZ", "BJ"}:
        raise ValueError(f"unsupported market label: {market}")
    return normalized


def market_from_label(label: str) -> Market:
    normalized = market_label(label)
    return Market[normalized]


def normalize_code(code: str) -> str:
    normalized = str(code).strip()
    if not re.fullmatch(r"\d{6}", normalized):
        raise ValueError("code must contain six digits")
    return normalized


def to_symbol(market: Market | str, code: str) -> str:
    return f"{market_label(market)}{normalize_code(code)}"


def parse_symbol(symbol: str) -> tuple[str, str]:
    normalized = symbol.strip().upper()
    match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", normalized)
    if match is None:
        raise ValueError("symbol must use SH, SZ, or BJ prefix with six digits")
    return match.group(1), match.group(2)


def is_a_share(market: Market | str, code: str) -> bool:
    normalized_code = normalize_code(code)
    market_enum = market if isinstance(market, Market) else market_from_label(market)
    prefixes = _A_SHARE_PREFIXES.get(market_enum, ())
    return any(normalized_code.startswith(prefix) for prefix in prefixes)
