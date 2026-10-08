from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from workbench.providers.eastmoney.security_lookup import normalize_em_symbol

StockBoard = Literal["popularity", "surge"]


@dataclass(frozen=True)
class EastMoneyHotStockRow:
    rank: int
    symbol: str
    code: str
    name: str
    price: float | None
    change_pct: float | None
    rank_change: int | None = None


class EastMoneyHotRankProvider:
    rank_base = "https://emappdata.eastmoney.com/stockrank"
    default_payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
    }

    def fetch_stock_rank(
        self,
        board: StockBoard,
        *,
        page_size: int = 100,
    ) -> list[EastMoneyHotStockRow]:
        path = "getAllCurrentList" if board == "popularity" else "getAllHisRcList"
        payload = {
            **self.default_payload,
            "pageNo": 1,
            "pageSize": page_size,
        }
        rows = self._post_rank(path, payload)
        if not rows:
            return []
        result: list[EastMoneyHotStockRow] = []
        for index, row in enumerate(rows):
            sc = str(row.get("sc") or "").strip().upper()
            if not sc:
                continue
            symbol, code = normalize_em_symbol(sc)
            rank = _to_int(row.get("rk")) or (index + 1)
            rank_change = _to_int(row.get("hrc")) if board == "surge" else _to_int(row.get("hisRc"))
            result.append(
                EastMoneyHotStockRow(
                    rank=rank,
                    symbol=symbol,
                    code=code,
                    name=code,
                    price=None,
                    change_pct=None,
                    rank_change=rank_change,
                )
            )
        return result

    def _post_rank(self, path: str, payload: dict) -> list[dict]:
        response = self._request(
            "POST",
            f"{self.rank_base}/{path}",
            json=payload,
            headers={"Referer": "https://guba.eastmoney.com/rank/"},
        )
        data = response.get("data")
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    @staticmethod
    def _request(method: str, url: str, **kwargs):
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the East Money hot rank provider") from exc

        headers = dict(kwargs.pop("headers", {}) or {})
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
                    raise RuntimeError("eastmoney hot rank response is not valid JSON")
                return payload
            except Exception as exc:
                last_error = exc
                if attempt >= 2:
                    break
        raise RuntimeError(f"eastmoney hot rank request failed: {last_error}") from last_error


def _symbol_to_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if len(normalized) > 2 and normalized[:2] in {"SH", "SZ", "BJ"}:
        return normalized[2:]
    return normalized


def _to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:  # NaN
        return None
    return parsed
