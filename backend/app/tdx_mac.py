from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from easy_tdx import MacClient
from easy_tdx.mac.enums import BoardType

BOARD_TYPE_MAP = {
    "HY": BoardType.HY,
    "HY2": BoardType.HY2,
    "GN": BoardType.GN,
    "FG": BoardType.FG,
    "DQ": BoardType.DQ,
    "ALL": BoardType.ALL,
}


def _today_int() -> int:
    return int(datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))


def _fmt_time(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    s = str(value)
    return s[:5] if len(s) >= 5 else s


def _change_pct(price: float, pre_close: float) -> float:
    if not pre_close:
        return 0.0
    return round((price - pre_close) / pre_close * 100, 2)


def momentum_to_main_flow(tick_df, official_main_net: float) -> list[dict[str, Any]]:
    """Convert board index tick momentum into scaled main-force minute curve."""
    if tick_df is None or len(tick_df) == 0:
        return []
    cum_raw = tick_df["momentum"].astype(float).cumsum()
    last_raw = float(cum_raw.iloc[-1]) if len(cum_raw) else 0.0
    if official_main_net and abs(last_raw) > 1e-9:
        scale = float(official_main_net) / last_raw
    elif abs(last_raw) > 1e-9:
        scale = 1e8
    else:
        scale = 0.0

    flow: list[dict[str, Any]] = []
    prev = 0.0
    for i in range(len(tick_df)):
        t = _fmt_time(tick_df.iloc[i]["time"])
        cum_v = float(cum_raw.iloc[i]) * scale
        flow.append(
            {
                "time": t,
                "main_net": round(cum_v - prev, 2),
                "cum_main": round(cum_v, 2),
                "cum_net": round(cum_v, 2),
            }
        )
        prev = cum_v
    return flow


class MacBoardProvider:
    """通达信 MAC 协议：板块列表、官方主力汇总、指数分时 momentum 曲线。"""

    def __init__(self) -> None:
        self._client: MacClient | None = None
        self._host: str | None = None
        self._meta_cache: dict[str, dict[str, Any]] = {}

    def _ensure(self) -> MacClient:
        if self._client is None:
            self._client = MacClient.from_best_host()
            host = getattr(self._client, "_host", None)
            port = getattr(self._client, "_port", 7727)
            if host:
                self._host = f"{host}:{port}"
        return self._client

    @property
    def host_label(self) -> str | None:
        return self._host

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _build_board_row(
        self,
        client: MacClient,
        code: str,
        name: str,
        *,
        price: float = 0.0,
        pre_close: float = 0.0,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        today = _today_int()
        try:
            summary = client.get_board_summary(code)
            main_net = float(summary.get("main_net_amount") or 0.0)
            tick = client.get_tick_chart(market=1, code=code, date=None)
            if tick is None or tick.empty:
                tick = client.get_tick_chart(market=1, code=code, date=today)
            flow = momentum_to_main_flow(tick, main_net)
            if not price and not tick.empty:
                price = float(tick.iloc[-1].get("price") or 0.0)
            row = {
                "id": code,
                "name": name or code,
                "code": code,
                "source": "tdx_mac",
                "change_pct": _change_pct(price, pre_close),
                "amount": float(summary.get("amount") or 0.0),
                "cum_main": main_net,
                "cum_net": main_net,
                "main_net_amount": main_net,
                "up_count": int(summary.get("up_count") or 0),
                "down_count": int(summary.get("down_count") or 0),
                "count": int(summary.get("member_count") or 0),
            }
            return row, flow
        except Exception:
            return None, []

    def fetch_board_flow(
        self,
        code: str,
        name: str = "",
        *,
        price: float = 0.0,
        pre_close: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Fetch today's sector intraday curve from MAC index tick momentum."""
        client = self._ensure()
        _, flow = self._build_board_row(client, code, name or code, price=price, pre_close=pre_close)
        return flow

    def _refresh_meta_cache(self, board_types: tuple[str, ...] = ("HY", "GN", "HY2")) -> None:
        client = self._ensure()
        cache: dict[str, dict[str, Any]] = {}
        for bt in board_types:
            btype = BOARD_TYPE_MAP.get(bt.upper(), BoardType.HY)
            df = client.get_board_list(board_type=btype, count=10000)
            if df is None or df.empty:
                continue
            for _, item in df.iterrows():
                code = str(item.get("code") or "").strip()
                if not code.startswith(("88", "89")):
                    continue
                cache[code] = {
                    "id": code,
                    "name": str(item.get("name") or code).strip(),
                    "price": float(item.get("price") or 0.0),
                    "pre_close": float(item.get("pre_close") or 0.0),
                    "change_pct": _change_pct(
                        float(item.get("price") or 0.0),
                        float(item.get("pre_close") or 0.0),
                    ),
                }
        self._meta_cache = cache

    def list_board_catalog(
        self,
        *,
        board_type: str = "HY",
        query: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        client = self._ensure()
        btype = BOARD_TYPE_MAP.get(board_type.upper(), BoardType.HY)
        df = client.get_board_list(board_type=btype, count=10000)
        if df is None or df.empty:
            return []
        q = (query or "").strip().lower()
        out: list[dict[str, Any]] = []
        for _, item in df.iterrows():
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or code).strip()
            if not code.startswith(("88", "89")):
                continue
            if q and q not in code.lower() and q not in name.lower():
                continue
            price = float(item.get("price") or 0.0)
            pre_close = float(item.get("pre_close") or 0.0)
            out.append(
                {
                    "id": code,
                    "name": name,
                    "change_pct": _change_pct(price, pre_close),
                }
            )
        out.sort(key=lambda x: x["name"])
        return out[:limit]

    def _build_board_summary_row(
        self,
        client: MacClient,
        code: str,
        name: str,
        *,
        price: float = 0.0,
        pre_close: float = 0.0,
    ) -> dict[str, Any] | None:
        try:
            summary = client.get_board_summary(code)
            main_net = float(summary.get("main_net_amount") or 0.0)
            if not price and pre_close:
                price = pre_close
            return {
                "id": code,
                "name": name or code,
                "code": code,
                "source": "tdx_mac",
                "change_pct": _change_pct(price, pre_close),
                "price": price,
                "amount": float(summary.get("amount") or 0.0),
                "cum_main": main_net,
                "cum_net": main_net,
                "main_net_amount": main_net,
                "up_count": int(summary.get("up_count") or 0),
                "down_count": int(summary.get("down_count") or 0),
                "count": int(summary.get("member_count") or 0),
            }
        except Exception:
            return None

    def fetch_board_summaries_by_codes(self, boards: list[dict[str, str]]) -> list[dict[str, Any]]:
        if not boards:
            return []
        if not self._meta_cache:
            self._refresh_meta_cache()
        client = self._ensure()
        rows: list[dict[str, Any]] = []
        for item in boards:
            code = str(item.get("id") or item.get("code") or "").strip()
            if not code:
                continue
            meta = self._meta_cache.get(code, {})
            name = str(item.get("name") or meta.get("name") or code)
            row = self._build_board_summary_row(
                client,
                code,
                name,
                price=float(meta.get("price") or 0.0),
                pre_close=float(meta.get("pre_close") or 0.0),
            )
            if row:
                rows.append(row)
        return rows

    def fetch_board_summaries_universe(
        self,
        *,
        board_type: str = "HY",
        count: int = 12,
    ) -> list[dict[str, Any]]:
        client = self._ensure()
        btype = BOARD_TYPE_MAP.get(board_type.upper(), BoardType.HY)
        df = client.get_board_list(board_type=btype, count=max(count * 3, 30))
        if df is None or df.empty:
            return []

        rows: list[dict[str, Any]] = []
        for _, item in df.iterrows():
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or code).strip()
            if not code.startswith(("88", "89")):
                continue
            price = float(item.get("price") or 0.0)
            pre_close = float(item.get("pre_close") or 0.0)
            row = self._build_board_summary_row(client, code, name, price=price, pre_close=pre_close)
            if row:
                rows.append(row)

        rows.sort(key=lambda x: float(x.get("cum_main") or 0), reverse=True)
        return rows[:count]

    def fetch_boards_by_codes(
        self,
        boards: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        if not boards:
            return [], {}
        if not self._meta_cache:
            self._refresh_meta_cache()
        client = self._ensure()
        rows: list[dict[str, Any]] = []
        flows: dict[str, list[dict[str, Any]]] = {}
        for item in boards:
            code = str(item.get("id") or item.get("code") or "").strip()
            if not code:
                continue
            meta = self._meta_cache.get(code, {})
            name = str(item.get("name") or meta.get("name") or code)
            row, flow = self._build_board_row(
                client,
                code,
                name,
                price=float(meta.get("price") or 0.0),
                pre_close=float(meta.get("pre_close") or 0.0),
            )
            if row:
                rows.append(row)
                flows[code] = flow
        return rows, flows

    def fetch_board_universe(
        self,
        *,
        board_type: str = "HY",
        count: int = 12,
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        client = self._ensure()
        btype = BOARD_TYPE_MAP.get(board_type.upper(), BoardType.HY)
        df = client.get_board_list(board_type=btype, count=max(count * 3, 30))
        if df is None or df.empty:
            return [], {}

        rows: list[dict[str, Any]] = []
        flows: dict[str, list[dict[str, Any]]] = {}

        for _, item in df.iterrows():
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or code).strip()
            if not code.startswith(("88", "89")):
                continue
            price = float(item.get("price") or 0.0)
            pre_close = float(item.get("pre_close") or 0.0)
            row, flow = self._build_board_row(client, code, name, price=price, pre_close=pre_close)
            if row:
                flows[code] = flow
                rows.append(row)

        rows.sort(key=lambda x: float(x.get("cum_main") or 0), reverse=True)
        rows = rows[:count]
        flows = {r["id"]: flows[r["id"]] for r in rows if r["id"] in flows}
        return rows, flows

    def fetch_stock_main_net(self, market: int, code: str) -> float:
        client = self._ensure()
        df = client.get_capital_flow(market=market, code=code)
        if df is None or df.empty:
            return 0.0
        row = df.iloc[0]
        if "main_net" in df.columns:
            return float(row.get("main_net") or 0.0)
        main_in = float(row.get("main_in") or 0.0)
        main_out = float(row.get("main_out") or 0.0)
        return main_in - main_out

    def fetch_stock_name(self, market: int, code: str) -> str:
        client = self._ensure()
        try:
            from easy_tdx.mac.commands.symbol_tick_chart import SymbolTickChartCmd

            chart = client._execute(SymbolTickChartCmd(market, code, None))
            if chart and chart.name:
                name = chart.name.strip().replace("\x00", "")
                if name:
                    return name
        except Exception:
            pass
        return code

    def fetch_stock_flow(
        self,
        market: int,
        code: str,
        *,
        symbol: str | None = None,
        transactions_fetcher=None,
        thresholds: dict[str, float] | None = None,
    ) -> tuple[float, list[dict[str, Any]]]:
        """MAC 官方当日主力 + 分笔分时形状，并按官方总额校准（与通达信 APP 同源）。"""
        from .fund_flow import calibrate_flow_to_main_net, estimate_fund_flow_minutes, synthetic_main_flow

        main_net = self.fetch_stock_main_net(market, code)
        client = self._ensure()
        today = _today_int()
        flow: list[dict[str, Any]] = []

        try:
            tick = client.get_tick_chart(market=market, code=code, date=None)
            if tick is None or tick.empty:
                tick = client.get_tick_chart(market=market, code=code, date=today)
            mom_sum = float(tick["momentum"].astype(float).sum()) if tick is not None and not tick.empty else 0.0
            if abs(mom_sum) > 1e-6:
                flow = momentum_to_main_flow(tick, main_net)
        except Exception:
            flow = []

        if (not flow or abs(float(flow[-1].get("cum_main") or 0)) < 1e-6) and transactions_fetcher and symbol and thresholds:
            try:
                txs = transactions_fetcher(symbol, count=2000)
                flow = estimate_fund_flow_minutes(txs, thresholds)
            except Exception:
                flow = []

        if flow:
            flow = calibrate_flow_to_main_net(flow, main_net)
            return main_net, flow
        if abs(main_net) > 1e-6:
            return main_net, synthetic_main_flow(main_net)
        return main_net, []

    def fetch_board_members(self, board_code: str, limit: int = 30) -> list[dict[str, Any]]:
        client = self._ensure()
        df = client.get_board_members(board_code, count=limit)
        if df is None or df.empty:
            return []
        out = []
        for _, row in df.iterrows():
            m = int(row.get("market") or 1)
            code = str(row.get("code") or "")
            prefix = {0: "SZ", 1: "SH", 2: "BJ"}.get(m, "SH")
            main_net = float(row.get("main_net_amount") or 0.0)
            price = float(row.get("close") or row.get("price") or 0.0)
            pre = float(row.get("pre_close") or 0.0)
            out.append(
                {
                    "symbol": f"{prefix}{code}",
                    "code": code,
                    "name": str(row.get("name") or code),
                    "cum_main": main_net,
                    "cum_net": main_net,
                    "quote": {
                        "price": price,
                        "change_pct": _change_pct(price, pre),
                    },
                }
            )
        return out
