from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .fund_flow import estimate_fund_flow_minutes
from .local_member import (
    DEFAULT_COLORS,
    LocalMemberStore,
    sector_id_from_code,
    stock_id_from_symbol,
    symbol_from_stock_id,
)
from .service import BoardService
from .tdx_local import split_symbol
from .trading_session import (
    EXPECTED_TRADING_MINUTES,
    local_now,
    public_trading_session_payload,
    resolve_trade_date,
    trading_session_status,
)

MARKET_FLOW_LINES = [
    {"key": "main", "displayName": "主力", "color": "#ee6666", "visible": True, "sortOrder": 1},
    {"key": "super_large", "displayName": "超大单", "color": "#5470c6", "visible": True, "sortOrder": 2},
    {"key": "large", "displayName": "大单", "color": "#91cc75", "visible": True, "sortOrder": 3},
    {"key": "medium", "displayName": "中单", "color": "#fac858", "visible": True, "sortOrder": 4},
    {"key": "small", "displayName": "小单", "color": "#73c0de", "visible": True, "sortOrder": 5},
]


class StockCatalog:
    def __init__(self, service: BoardService):
        self.service = service
        self._rows: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._rows is not None:
                return self._rows
            client = self.service.client
            client.ensure()
            rows: list[dict[str, Any]] = []
            for market in (0, 1, 2):
                prefix = {0: "SZ", 1: "SH", 2: "BJ"}.get(market, "SZ")
                start = 0
                while start < 20000:
                    batch = client.api.get_security_list(market, start) or []
                    if not batch:
                        break
                    for item in batch:
                        code = str(item.get("code") or "")
                        name = str(item.get("name") or code)
                        if len(code) != 6 or not code.isdigit():
                            continue
                        symbol = f"{prefix}{code}"
                        rows.append(
                            {
                                "id": stock_id_from_symbol(symbol),
                                "stockCode": code,
                                "market": prefix,
                                "displayName": name,
                                "sourceName": name,
                                "sourceCode": code,
                                "symbol": symbol,
                            }
                        )
                    if len(batch) < 1000:
                        break
                    start += len(batch)
            self._rows = rows
            return rows

    def search(self, q: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
        rows = self._ensure()
        query = (q or "").strip().lower()
        if query:
            filtered = [
                row
                for row in rows
                if query in row["stockCode"].lower()
                or query in row["displayName"].lower()
                or query in row["symbol"].lower()
            ]
        else:
            filtered = rows
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        start = (page - 1) * page_size
        chunk = filtered[start : start + page_size]
        for idx, row in enumerate(chunk):
            row = dict(row)
            row["sortOrder"] = start + idx
            row["color"] = DEFAULT_COLORS[(start + idx) % len(DEFAULT_COLORS)]
            row["realtimeFetchEnabled"] = True
            chunk[idx] = row
        return {
            "stocks": chunk,
            "total": len(filtered),
            "page": page,
            "pageSize": page_size,
        }


class DaACompatAPI:
    def __init__(self, service: BoardService):
        self.service = service
        self.member = LocalMemberStore(service.project_root)
        self.catalog = StockCatalog(service)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _flow_to_series(self, rows: list[dict[str, Any]], *, change_pct: float | None = None) -> list[dict[str, Any]]:
        series = []
        for row in rows:
            point = {
                "time": str(row.get("time")),
                "mainNetInflow": float(row.get("cum_main") or row.get("cum_net") or 0),
                "sampled": True,
            }
            if change_pct is not None:
                point["changePct"] = change_pct
            series.append(point)
        return series

    def _completeness(self, series: list[dict[str, Any]]) -> dict[str, Any]:
        minutes = {p["time"] for p in series if p.get("time")}
        sampled = len(minutes)
        return {
            "sampledMinutes": sampled,
            "expectedMinutes": EXPECTED_TRADING_MINUTES,
            "ratio": round(sampled / EXPECTED_TRADING_MINUTES, 4) if EXPECTED_TRADING_MINUTES else 0,
        }

    def _sector_rows_for_flow(self) -> list[dict[str, Any]]:
        configs = self.member.get_sector_configs()
        if configs:
            return configs
        snap = self.service.get_snapshot()
        sectors = snap.get("sectors") or []
        rows = []
        for idx, sec in enumerate(sectors):
            code = str(sec.get("id") or sec.get("code") or "")
            if not code:
                continue
            rows.append(
                {
                    "id": sector_id_from_code(code),
                    "displayName": str(sec.get("name") or code),
                    "sectorType": str(snap.get("board_type") or "HY"),
                    "sourceName": str(sec.get("name") or code),
                    "sourceCode": code,
                    "sortOrder": idx,
                    "color": DEFAULT_COLORS[idx % len(DEFAULT_COLORS)],
                    "displayEnabled": True,
                    "realtimeFetchEnabled": True,
                    "customColor": None,
                }
            )
        return rows

    def _build_sector_flow_snapshot(
        self,
        *,
        date: str,
        sector_rows: list[dict[str, Any]] | None = None,
        sector_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        rows = sector_rows or self._sector_rows_for_flow()
        if sector_ids:
            allowed = set(sector_ids)
            rows = [row for row in rows if row["id"] in allowed]
        if not rows:
            return self._empty_sector_flow(date)

        today = resolve_trade_date()
        snap = self.service.get_snapshot()
        sector_meta = {str(s.get("id")): s for s in snap.get("sectors") or []}
        codes = [str(row.get("sourceCode") or row["id"]) for row in rows]
        flows = self.service.build_sector_flows_for_date(
            date,
            codes,
            live_sectors=list(sector_meta.values()),
        )

        sectors_out = []
        for rank, row in enumerate(rows, start=1):
            code = str(row.get("sourceCode") or row["id"])
            meta = sector_meta.get(code, {})
            flow_rows = flows.get(code) or []
            change_pct = meta.get("change_pct")
            if change_pct is None:
                change_pct = row.get("changePct")
            series = self._flow_to_series(flow_rows, change_pct=change_pct)
            final = float(series[-1]["mainNetInflow"]) if series else float(meta.get("cum_main") or 0)
            sectors_out.append(
                {
                    "id": row["id"],
                    "name": row["displayName"],
                    "sectorType": row.get("sectorType") or "selected",
                    "sortOrder": row.get("sortOrder") or rank,
                    "color": row.get("customColor") or row.get("color") or DEFAULT_COLORS[(rank - 1) % len(DEFAULT_COLORS)],
                    "rank": rank,
                    "finalNetInflow": final,
                    "unit": "yuan",
                    "changePct": change_pct,
                    "series": series,
                }
            )

        sampled_minutes = max(
            (self._completeness(sec["series"])["sampledMinutes"] for sec in sectors_out),
            default=0,
        )
        return {
            "date": date,
            "source": "tdx_mac",
            "sectorType": "selected",
            "status": "partial",
            "sampleInterval": "1min",
            "fetchedAt": self._now_iso(),
            "completeness": {
                "sampledMinutes": sampled_minutes,
                "expectedMinutes": EXPECTED_TRADING_MINUTES,
                "ratio": round(sampled_minutes / EXPECTED_TRADING_MINUTES, 4) if EXPECTED_TRADING_MINUTES else 0,
            },
            "sectors": sectors_out,
        }

    @staticmethod
    def _empty_sector_flow(date: str) -> dict[str, Any]:
        return {
            "date": date,
            "source": "tdx_mac",
            "sectorType": "selected",
            "status": "partial",
            "sampleInterval": "1min",
            "fetchedAt": None,
            "completeness": {
                "sampledMinutes": 0,
                "expectedMinutes": EXPECTED_TRADING_MINUTES,
                "ratio": 0,
            },
            "sectors": [],
        }

    def _build_stock_flow_snapshot(
        self,
        *,
        date: str,
        stock_rows: list[dict[str, Any]] | None = None,
        stock_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        rows = stock_rows or self.member.get_stock_configs()
        if stock_ids:
            allowed = set(stock_ids)
            rows = [row for row in rows if row["id"] in allowed]
        if not rows:
            return {
                "date": date,
                "unit": "yuan",
                "source": "tdx_mac",
                "fetchedAt": None,
                "completeness": {
                    "stocks": 0,
                    "samples": 0,
                    "sampledMinutes": 0,
                    "expectedMinutes": EXPECTED_TRADING_MINUTES,
                    "ratio": 0,
                },
                "stocks": [],
            }

        snap = self.service.get_snapshot()
        cached_flows = snap.get("stock_flows") or {}
        thresholds = snap.get("thresholds") or {}
        stocks_out = []
        total_samples = 0
        max_minutes = 0

        for rank, row in enumerate(rows, start=1):
            symbol = f"{row['market']}{row['stockCode']}"
            flow_rows = cached_flows.get(symbol) or []
            change_pct = None
            if not flow_rows:
                try:
                    market, code = split_symbol(symbol)
                    main_net = self.service.mac.fetch_stock_main_net(market, code)
                    client = self.service.mac._ensure()
                    tick = client.get_tick_chart(market=market, code=code, date=None)
                    from .tdx_mac import momentum_to_main_flow

                    flow_rows = momentum_to_main_flow(tick, main_net)
                    if not flow_rows:
                        txs = self.service.client.transactions(symbol, count=2000)
                        flow_rows = estimate_fund_flow_minutes(txs, thresholds)
                    q = (snap.get("quotes") or {}).get(symbol)
                    if q:
                        change_pct = q.get("change_pct")
                except Exception:
                    flow_rows = []
            series = self._flow_to_series(flow_rows, change_pct=change_pct)
            total_samples += len(series)
            max_minutes = max(max_minutes, len({p["time"] for p in series}))
            final = float(series[-1]["mainNetInflow"]) if series else 0.0
            stocks_out.append(
                {
                    "id": row["id"],
                    "name": row["displayName"],
                    "code": row["stockCode"],
                    "market": row["market"],
                    "sortOrder": row.get("sortOrder") or rank,
                    "color": row.get("customColor") or row.get("color") or DEFAULT_COLORS[(rank - 1) % len(DEFAULT_COLORS)],
                    "finalNetInflow": final,
                    "changePct": change_pct,
                    "series": [{"time": p["time"], "mainNetInflow": p["mainNetInflow"], "sampled": True} for p in series],
                }
            )

        return {
            "date": date,
            "unit": "yuan",
            "source": "tdx_mac",
            "fetchedAt": self._now_iso(),
            "completeness": {
                "stocks": len(stocks_out),
                "samples": total_samples,
                "sampledMinutes": max_minutes,
                "expectedMinutes": EXPECTED_TRADING_MINUTES,
                "ratio": round(max_minutes / EXPECTED_TRADING_MINUTES, 4) if EXPECTED_TRADING_MINUTES else 0,
            },
            "stocks": stocks_out,
        }

    def _build_market_flow(self, date: str) -> dict[str, Any]:
        thresholds = self.service.get_snapshot().get("thresholds") or {}
        try:
            txs = self.service.client.transactions("SH999999", count=4000)
            rows = estimate_fund_flow_minutes(txs, thresholds)
        except Exception:
            rows = []

        points = []
        for row in rows:
            points.append(
                {
                    "time": row["time"],
                    "mainNetInflow": float(row.get("cum_main") or 0),
                    "superLargeNetInflow": float(row.get("cum_super") or 0),
                    "largeNetInflow": float(row.get("cum_large") or 0),
                    "mediumNetInflow": float(row.get("cum_medium") or 0),
                    "smallNetInflow": float(row.get("cum_small") or 0),
                }
            )
        minutes = {p["time"] for p in points}
        sampled = len(minutes)
        return {
            "date": date,
            "unit": "yuan",
            "source": "tdx_tick",
            "marketScope": "hs",
            "marketScopeLabel": "沪深",
            "fetchedAt": self._now_iso(),
            "message": "通达信分笔分档推算，非东财口径",
            "completeness": {
                "samples": len(points),
                "sampledMinutes": sampled,
                "expectedMinutes": EXPECTED_TRADING_MINUTES,
                "ratio": round(sampled / EXPECTED_TRADING_MINUTES, 4) if EXPECTED_TRADING_MINUTES else 0,
                "source": "tdx_tick",
            },
            "lineConfigs": MARKET_FLOW_LINES,
            "points": points,
        }

    def list_dates(self) -> list[str]:
        today = resolve_trade_date()
        out = [today]
        now = local_now()
        for delta in range(1, 8):
            day = (now.date().fromordinal(now.date().toordinal() - delta)).isoformat()
            out.append(day)
        return out

    def public_web_client_config(self) -> dict[str, Any]:
        return {
            "webClientName": "通达信板块脉搏",
            "sectorSelectionLimit": self.member.sector_limit,
            "stockSelectionLimit": self.member.stock_limit,
            "etfSelectionLimit": 15,
            "grayEnabled": False,
            "sectorGrayEnabled": False,
            "stockGrayEnabled": False,
            "auctionBoardEnabled": False,
            "memberCustomColorCloudEnabled": False,
            "updatedAt": self._now_iso(),
        }

    def member_me(self) -> dict[str, Any]:
        return {
            "member": {
                "id": 1,
                "username": "local",
                "nickname": "本地用户",
                "avatarUrl": None,
                "phone": None,
                "email": None,
                "level": "local",
                "status": "active",
                "createdAt": self._now_iso(),
                "lastLoginAt": self._now_iso(),
                "agreementAcceptedAt": self._now_iso(),
                "agreementVersion": "local_v1",
                "subscriptionExpiresAt": None,
                "subscriptionRemainingDays": 9999,
                "subscriptionStatus": "active",
                "totalRechargedDays": 0,
                "lastRechargedAt": None,
                "sectorViewBaseLimit": self.member.sector_limit,
                "sectorViewExtraLimit": 0,
                "sectorViewLimit": self.member.sector_limit,
                "sectorQuotaPackages": [],
                "stockAccessEnabled": True,
                "stockAccessExpiresAt": None,
                "stockAccessStatus": "active",
                "grayAccessEnabled": False,
                "grayAccessExpiresAt": None,
                "grayAccessStatus": "disabled",
                "sectorGrayAccessEnabled": False,
                "stockGrayAccessEnabled": False,
                "customColorCloudSyncEnabled": False,
            }
        }

    def search_sectors(self, q: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
        boards = self.service.list_board_catalog(board_type="HY", query=q, limit=500)
        if not boards:
            boards = self.service.list_board_catalog(board_type="GN", query=q, limit=500)
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        start = (page - 1) * page_size
        chunk = boards[start : start + page_size]
        sectors = []
        for idx, board in enumerate(chunk):
            code = str(board["id"])
            sectors.append(
                {
                    "id": sector_id_from_code(code),
                    "displayName": board["name"],
                    "sectorType": "HY",
                    "sourceName": board["name"],
                    "sourceCode": code,
                    "sortOrder": start + idx,
                    "color": DEFAULT_COLORS[(start + idx) % len(DEFAULT_COLORS)],
                    "displayEnabled": True,
                    "realtimeFetchEnabled": True,
                    "customColor": None,
                }
            )
        return {
            "sectors": sectors,
            "total": len(boards),
            "page": page,
            "pageSize": page_size,
        }

    def save_sector_trend(self, sector_ids: list[int], custom_colors: dict[int, str | None] | None = None) -> dict[str, Any]:
        lookup: dict[int, dict[str, Any]] = {}
        existing = {row["id"]: row for row in self.member.get_sector_configs()}
        for sid in sector_ids:
            prev = existing.get(sid)
            code = str(prev.get("sourceCode") if prev else sid)
            name = str(prev.get("displayName") if prev else code)
            if not prev or name == code:
                for board_type in ("HY", "GN", "HY2"):
                    boards = self.service.list_board_catalog(board_type=board_type, query=code, limit=20)
                    hit = next((b for b in boards if str(b["id"]) == code), None)
                    if hit:
                        name = hit["name"]
                        break
            lookup[sid] = {"sourceCode": code, "displayName": name, "id": sid}
        sectors = self.member.set_sector_configs(sector_ids, catalog_lookup=lookup, custom_colors=custom_colors)
        boards = [{"id": str(s["sourceCode"]), "name": s["displayName"]} for s in sectors]
        self.service.set_selected_boards(boards)
        self.service.refresh_once()
        return self.member.sector_trend_options()

    def save_stocks(self, stock_ids: list[int], custom_colors: dict[int, str | None] | None = None) -> dict[str, Any]:
        lookup = {}
        for sid in stock_ids:
            symbol = symbol_from_stock_id(sid)
            lookup[sid] = {"symbol": symbol, "displayName": symbol[2:], "id": sid}
        self.member.set_stock_configs(stock_ids, catalog_lookup=lookup, custom_colors=custom_colors)
        self.service.refresh_once()
        return self.member.stock_options_payload()

    def sync_default_sectors_from_config(self) -> None:
        if self.member.get_sector_configs():
            return
        selected = self.service.get_selected_boards()
        if not selected:
            return
        ids = [sector_id_from_code(str(b["id"])) for b in selected]
        names = {sector_id_from_code(str(b["id"])): str(b.get("name") or b["id"]) for b in selected}
        lookup = {
            sid: {"sourceCode": str(sid), "displayName": names.get(sid, str(sid)), "id": sid}
            for sid in ids
        }
        self.member.set_sector_configs(ids, catalog_lookup=lookup)

    def sync_default_stocks_from_config(self) -> None:
        if self.member.get_stock_configs():
            return
        watch = self.service._resolve_watchlist()
        ids = [stock_id_from_symbol(sym) for sym in watch[: self.member.stock_limit]]
        lookup = {sid: {"symbol": symbol_from_stock_id(sid), "id": sid} for sid in ids}
        self.member.set_stock_configs(ids, catalog_lookup=lookup)
