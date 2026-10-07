from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StockBoard = Literal["popularity", "surge"]
BoardType = Literal["concept", "industry"]

THS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": "https://eq.10jqka.com.cn",
    "Referer": "https://eq.10jqka.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

THS_MARKET_PREFIX = {
    17: "SH",
    18: "SH",
    33: "SZ",
    34: "SZ",
    151: "BJ",
}


@dataclass(frozen=True)
class TonghuashunHotStockRow:
    rank: int
    symbol: str
    code: str
    name: str
    change_pct: float | None
    hot_value: float | None
    rank_change: int | None = None


@dataclass(frozen=True)
class TonghuashunHotBoardRow:
    rank: int
    board_code: str
    name: str
    change_pct: float | None
    hot_value: float | None
    rank_change: int | None = None


class TonghuashunHotRankProvider:
    stock_api = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
    plate_api = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/plate"

    def fetch_stock_rank(self, board: StockBoard) -> list[TonghuashunHotStockRow]:
        list_type = "normal" if board == "popularity" else "skyrocket"
        rows = self._fetch_stock_rows(list_type=list_type, period="hour")
        if not rows:
            return []
        rank_changes = _rank_change_map(self._fetch_stock_rows(list_type=list_type, period="day"))
        result: list[TonghuashunHotStockRow] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            market = _to_int(row.get("market"))
            prefix = THS_MARKET_PREFIX.get(market or -1, "SH" if code.startswith("6") else "SZ")
            result.append(
                TonghuashunHotStockRow(
                    rank=_to_int(row.get("order")) or len(result) + 1,
                    symbol=f"{prefix}{code}",
                    code=code,
                    name=str(row.get("name") or code).strip(),
                    change_pct=_to_float(row.get("rise_and_fall")),
                    hot_value=_to_float(row.get("rate")),
                    rank_change=rank_changes.get(code, _to_int(row.get("hot_rank_chg"))),
                )
            )
        return result

    def _fetch_stock_rows(self, *, list_type: str, period: str) -> list[dict]:
        payload = self._request(
            "GET",
            self.stock_api,
            params={"stock_type": "a", "type": period, "list_type": list_type},
        )
        rows = ((payload.get("data") or {}).get("stock_list")) if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_board_rank(self, board_type: BoardType) -> list[TonghuashunHotBoardRow]:
        payload = self._request(
            "GET",
            self.plate_api,
            params={"type": board_type},
        )
        rows = ((payload.get("data") or {}).get("plate_list")) if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        result: list[TonghuashunHotBoardRow] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            result.append(
                TonghuashunHotBoardRow(
                    rank=_to_int(row.get("order")) or len(result) + 1,
                    board_code=code,
                    name=str(row.get("name") or code).strip(),
                    change_pct=_to_float(row.get("rise_and_fall")),
                    hot_value=_to_float(row.get("rate")),
                    rank_change=_to_int(row.get("hot_rank_chg")),
                )
            )
        return result

    @staticmethod
    def _request(method: str, url: str, **kwargs):
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for the Tonghuashun hot rank provider") from exc

        response = requests.request(
            method,
            url,
            headers=THS_HEADERS,
            impersonate="chrome",
            timeout=20,
            **kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("tonghuashun hot rank response is not valid JSON")
        if payload.get("status_code") not in (0, None):
            message = str(payload.get("status_msg") or payload.get("message") or "unknown error")
            raise RuntimeError(f"tonghuashun hot rank upstream error: {message}")
        return payload


def _rank_change_map(rows: list[dict]) -> dict[str, int]:
    changes: dict[str, int] = {}
    for row in rows:
        code = str(row.get("code") or "").strip()
        change = _to_int(row.get("hot_rank_chg"))
        if not code or change is None:
            continue
        changes[code] = change
    return changes


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
    if parsed != parsed:
        return None
    return parsed
