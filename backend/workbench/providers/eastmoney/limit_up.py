from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EastMoneyLimitUpRow:
    symbol: str
    code: str
    name: str
    price: float | None
    change_pct: float | None
    board_days: int
    first_seal_time: str | None
    last_seal_time: str | None
    seal_amount: float | None
    broken_count: int | None
    industry: str | None
    turnover_rate: float | None
    limit_stats: str | None


class EastMoneyLimitUpProvider:
    limit_up_api = "https://push2ex.eastmoney.com/getTopicZTPool"
    broken_api = "https://push2ex.eastmoney.com/getTopicZBPool"
    default_params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": 0,
    }

    def fetch_limit_up_pool(self, trade_date: str, *, page_size: int = 500) -> list[EastMoneyLimitUpRow]:
        rows = self._fetch_pool(
            self.limit_up_api,
            trade_date,
            page_size=page_size,
            sort="lbc:desc",
        )
        return [self._parse_limit_up_row(row) for row in rows]

    def fetch_broken_pool(self, trade_date: str, *, page_size: int = 500) -> list[EastMoneyLimitUpRow]:
        rows = self._fetch_pool(
            self.broken_api,
            trade_date,
            page_size=page_size,
            sort="fbt:asc",
        )
        return [self._parse_broken_row(row) for row in rows]

    def _fetch_pool(
        self,
        api: str,
        trade_date: str,
        *,
        page_size: int,
        sort: str,
    ) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            api,
            params={
                **self.default_params,
                "pagesize": page_size,
                "sort": sort,
                "date": _normalize_trade_date(trade_date),
            },
        )
        pool = (response.get("data") or {}).get("pool")
        if not isinstance(pool, list):
            return []
        return [row for row in pool if isinstance(row, dict)]

    def _parse_limit_up_row(self, row: dict[str, Any]) -> EastMoneyLimitUpRow:
        code = str(row.get("c") or "").strip()
        return EastMoneyLimitUpRow(
            symbol=_to_symbol(code, row.get("m")),
            code=code,
            name=str(row.get("n") or code).strip(),
            price=_price_from_raw(row.get("p")),
            change_pct=_to_float(row.get("zdp")),
            board_days=max(_to_int(row.get("lbc")) or 1, 1),
            first_seal_time=_format_seal_time(row.get("fbt")),
            last_seal_time=_format_seal_time(row.get("lbt")),
            seal_amount=_to_float(row.get("fund")),
            broken_count=_to_int(row.get("zbc")),
            industry=_nullable_str(row.get("hybk")),
            turnover_rate=_to_float(row.get("hs")),
            limit_stats=_format_limit_stats(row.get("zttj")),
        )

    def _parse_broken_row(self, row: dict[str, Any]) -> EastMoneyLimitUpRow:
        code = str(row.get("c") or "").strip()
        return EastMoneyLimitUpRow(
            symbol=_to_symbol(code, row.get("m")),
            code=code,
            name=str(row.get("n") or code).strip(),
            price=_price_from_raw(row.get("p")),
            change_pct=_to_float(row.get("zdp")),
            board_days=0,
            first_seal_time=_format_seal_time(row.get("fbt")),
            last_seal_time=None,
            seal_amount=None,
            broken_count=max(_to_int(row.get("zbc")) or 1, 1),
            industry=_nullable_str(row.get("hybk")),
            turnover_rate=_to_float(row.get("hs")),
            limit_stats=_format_limit_stats(row.get("zttj")),
        )

    @staticmethod
    def _request(method: str, url: str, **kwargs):
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the East Money limit-up provider") from exc

        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Referer", "https://quote.eastmoney.com/ztb/detail")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    impersonate="chrome",
                    timeout=20,
                    **kwargs,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("eastmoney limit-up response is not valid JSON")
                return payload
            except Exception as exc:
                last_error = exc
                if attempt >= 2:
                    break
        raise RuntimeError(f"eastmoney limit-up request failed: {last_error}") from last_error


def _normalize_trade_date(trade_date: str) -> str:
    normalized = trade_date.strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"invalid trade_date: {trade_date}")
    return normalized


def _to_symbol(code: str, market: object) -> str:
    market_code = _to_int(market)
    if market_code == 1:
        return f"SH{code}"
    if market_code == 0:
        return f"SZ{code}"
    if market_code == 2 or code.startswith(("8", "4")):
        return f"BJ{code}"
    if code.startswith("6"):
        return f"SH{code}"
    return f"SZ{code}"


def _price_from_raw(value: object) -> float | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return parsed / 100.0


def _format_seal_time(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        digits = str(int(value)).zfill(6)
    except (TypeError, ValueError):
        return None
    return f"{digits[0:2]}:{digits[2:4]}"


def _format_limit_stats(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    days = _to_int(value.get("days"))
    count = _to_int(value.get("ct"))
    if days is None or count is None:
        return None
    return f"{days}天{count}板"


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed
