from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import yaml

from .intraday_store import IntradayStore
from .tdx_local import normalize_codes, split_symbol
from .tdx_mac import MacBoardProvider
from .tdx_quotes import TdxClient
from .trading_session import resolve_intraday_view_date, should_sample_intraday, trading_session_status

DISCLAIMER = (
    "板块/个股主力总额来自通达信 MAC 官方 main_net_amount；"
    "板块/个股分时均来自运行期间分钟采样持久化，与 APP 回放同口径；"
    "服务未覆盖时段无历史补拉；非东财口径。"
)

MIN_LIVE_STOCK_FLOW_POINTS = 5


class BoardService:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.project_root = config_path.parent
        self.selected_path = self.project_root / "selected_boards.yaml"
        self.selected_stocks_path = self.project_root / "selected_stocks.yaml"
        self.config = self._load_config()
        self.client = TdxClient()
        self.mac = MacBoardProvider()
        data_dir = self.project_root / "data"
        self.intraday = IntradayStore(data_dir / "intraday.db")
        self.lock = threading.RLock()
        self.snapshot: dict[str, Any] = {
            "updated_at": None,
            "error": None,
            "watchlist": [],
            "sectors": [],
            "quotes": {},
            "stock_flows": {},
            "sector_flows": {},
            "minutes": {},
            "disclaimer": DISCLAIMER,
            "thresholds": {"super": 1_000_000, "large": 200_000, "medium": 40_000},
            "data_source": "tdx_mac",
            "sector_mode": "auto",
            "selected_boards": [],
            "stock_mode": "empty",
            "selected_stocks": [],
        }
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._refresh_lock = threading.Lock()

    def _load_config(self) -> dict[str, Any]:
        with self.config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def reload_config(self) -> None:
        self.config = self._load_config()

    @property
    def tdx_root(self) -> Path:
        return Path(self.config.get("tdx_root") or r"C:\new_tdx64")

    @property
    def refresh_seconds(self) -> float:
        return float(self.config.get("refresh_seconds") or 4)

    @property
    def intraday_retention_days(self) -> int:
        return int(self.config.get("intraday_retention_days") or 15)

    def resolve_stock_view_date(self, requested: str | None = None) -> str:
        symbols = [s["symbol"] for s in self.get_selected_stocks()]
        return resolve_intraday_view_date(
            requested,
            symbols,
            lambda d, sym: bool(self.intraday.load_stock_series(d, sym)),
            self.intraday.get_latest_stock_date,
        )

    def resolve_sector_view_date(self, requested: str | None = None, sector_ids: list[str] | None = None) -> str:
        ids = sector_ids or [b["id"] for b in self.get_selected_boards()]
        return resolve_intraday_view_date(
            requested,
            ids,
            lambda d, sid: bool(self.intraday.load_sector_series(d, sid)),
            self.intraday.get_latest_sector_date,
        )

    def list_stock_intraday_dates(self, limit: int | None = None) -> list[str]:
        symbols = [s["symbol"] for s in self.get_selected_stocks()]
        cap = limit or self.intraday_retention_days
        return self.intraday.list_stock_dates(symbols=symbols if symbols else None, limit=cap)

    def list_sector_intraday_dates(self, sector_ids: list[str] | None = None, limit: int | None = None) -> list[str]:
        ids = sector_ids or [b["id"] for b in self.get_selected_boards()]
        cap = limit or self.intraday_retention_days
        return self.intraday.list_sector_dates(sector_ids=ids if ids else None, limit=cap)

    def build_sector_flows_for_date(
        self,
        trade_date: str,
        sector_ids: list[str],
        *,
        live_sectors: list[dict[str, Any]] | None = None,
    ) -> dict[str, list]:
        flows = self.intraday.load_series_for_sectors(trade_date, sector_ids)
        session = trading_session_status()
        is_today = trade_date == session["tradeDate"]
        can_supplement = is_today and session.get("marketStatus") in ("open", "lunch_break", "closed")
        live_map = {str(s.get("id")): s for s in (live_sectors or []) if s.get("id")}

        for sid in sector_ids:
            stored = flows.get(sid) or []
            if stored:
                continue
            if not can_supplement:
                continue
            live = live_map.get(sid)
            if not live:
                continue
            main_net = float(live.get("cum_main") or live.get("main_net_amount") or 0)
            if abs(main_net) < 1e-6:
                continue
            minute = "15:00" if session.get("marketStatus") == "closed" else session["currentMinute"]
            point: dict[str, Any] = {
                "time": minute,
                "main_net": main_net,
                "cum_main": main_net,
                "cum_net": main_net,
            }
            if live.get("price") is not None:
                point["price"] = float(live["price"])
            if live.get("change_pct") is not None:
                point["change_pct"] = float(live["change_pct"])
            flows[sid] = [point]
        return flows

    def build_stock_flows_for_date(
        self,
        trade_date: str,
        symbols: list[str],
        *,
        live_quotes: dict[str, dict[str, Any]] | None = None,
        live_main_nets: dict[str, float] | None = None,
    ) -> dict[str, list]:
        flows = self.intraday.load_series_for_symbols(trade_date, symbols)
        session = trading_session_status()
        is_today = trade_date == session["tradeDate"]
        can_fetch_live = is_today and session.get("marketStatus") in ("open", "lunch_break", "closed")
        thresholds = {
            **(self.snapshot.get("thresholds") or {}),
            **(self.config.get("order_thresholds") or {}),
        }
        for sym in symbols:
            stored = flows.get(sym) or []
            sparse = len(stored) < MIN_LIVE_STOCK_FLOW_POINTS
            if not can_fetch_live or (stored and not sparse):
                continue
            try:
                market, code = split_symbol(sym)
                main_net, flow = self.mac.fetch_stock_flow(
                    market,
                    code,
                    symbol=sym,
                    transactions_fetcher=self.client.transactions,
                    thresholds=thresholds,
                )
                if flow:
                    flows[sym] = flow
                    continue
            except Exception:
                pass
            if sparse and live_main_nets and sym in live_main_nets:
                main_net = float(live_main_nets.get(sym) or 0)
                if abs(main_net) > 1e-6:
                    from .fund_flow import synthetic_main_flow

                    flows[sym] = synthetic_main_flow(main_net)
        return flows

    def _archive_today_flows_if_closed(
        self,
        trade_date: str,
        sector_view_date: str,
        stock_view_date: str,
        sector_flows: dict[str, list],
        stock_flows: dict[str, list],
    ) -> None:
        session = trading_session_status()
        if not session.get("isTradingDay") or session.get("marketStatus") != "closed":
            return
        archived = False
        if stock_view_date == trade_date:
            for sym, flow in stock_flows.items():
                if flow:
                    self.intraday.replace_stock_flow(trade_date, sym, flow)
                    archived = True
        if archived:
            self.intraday.prune_old_dates(self.intraday_retention_days)

    def get_stock_intraday_detail(self, symbol: str, trade_date: str | None = None) -> dict[str, Any]:
        sym = symbol.upper().replace(".", "")
        date = trade_date or self.resolve_stock_view_date()
        session = trading_session_status()
        is_today = date == session.get("tradeDate")
        flow = self.intraday.load_series_for_symbols(date, [sym]).get(sym) or []
        if is_today and len(flow) < MIN_LIVE_STOCK_FLOW_POINTS and session.get("marketStatus") in (
            "open",
            "lunch_break",
            "closed",
        ):
            thresholds = {
                **(self.snapshot.get("thresholds") or {}),
                **(self.config.get("order_thresholds") or {}),
            }
            try:
                market, code = split_symbol(sym)
                _, live_flow = self.mac.fetch_stock_flow(
                    market,
                    code,
                    symbol=sym,
                    transactions_fetcher=self.client.transactions,
                    thresholds=thresholds,
                )
                if live_flow:
                    flow = live_flow
            except Exception:
                pass
        rows = self.intraday.load_stock_series(date, sym)
        last = rows[-1] if rows else {}
        snap = self.get_snapshot()
        quote = (snap.get("quotes") or {}).get(sym)
        if not quote and last:
            quote = {
                "price": last.get("price"),
                "change_pct": last.get("change_pct"),
            }
        return {
            "symbol": sym,
            "trade_date": date,
            "quote": quote,
            "fund_flow": flow,
            "snapshots": rows,
            "disclaimer": DISCLAIMER,
            "updated_at": snap.get("updated_at"),
        }

    def _normalize_board_item(self, item: Any) -> dict[str, str] | None:
        if isinstance(item, str):
            code = item.strip()
            if code.isdigit() and len(code) == 6:
                return {"id": code, "name": code}
            return None
        if isinstance(item, dict):
            code = str(item.get("id") or item.get("code") or "").strip()
            if not code:
                return None
            return {"id": code, "name": str(item.get("name") or code).strip()}
        return None

    def get_selected_boards(self) -> list[dict[str, str]]:
        boards: list[dict[str, str]] = []
        if self.selected_path.exists():
            with self.selected_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for item in data.get("boards") or []:
                norm = self._normalize_board_item(item)
                if norm:
                    boards.append(norm)
        if boards:
            return boards
        for item in self.config.get("default_selected_boards") or []:
            norm = self._normalize_board_item(item)
            if norm:
                boards.append(norm)
        return boards

    def set_selected_boards(self, boards: list[dict[str, str]]) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in boards:
            norm = self._normalize_board_item(item)
            if not norm or norm["id"] in seen:
                continue
            seen.add(norm["id"])
            cleaned.append(norm)
        payload = {"boards": cleaned}
        with self.selected_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        return cleaned

    def _normalize_stock_item(self, item: Any) -> dict[str, str] | None:
        if isinstance(item, str):
            codes = normalize_codes([item.strip()])
            if not codes:
                return None
            sym = codes[0]
            return {"symbol": sym, "name": sym}
        if isinstance(item, dict):
            raw = str(item.get("symbol") or item.get("id") or "").strip()
            if not raw:
                market = str(item.get("market") or "").strip().upper()
                code = str(item.get("stockCode") or item.get("code") or "").strip()
                if market and code:
                    raw = f"{market}{code}"
            codes = normalize_codes([raw]) if raw else []
            if not codes:
                return None
            sym = codes[0]
            return {"symbol": sym, "name": str(item.get("name") or sym).strip()}
        return None

    def get_selected_stocks(self) -> list[dict[str, str]]:
        stocks: list[dict[str, str]] = []
        if self.selected_stocks_path.exists():
            with self.selected_stocks_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for item in data.get("stocks") or []:
                norm = self._normalize_stock_item(item)
                if norm:
                    stocks.append(norm)
        if stocks:
            return stocks
        for item in self.config.get("default_selected_stocks") or []:
            norm = self._normalize_stock_item(item)
            if norm:
                stocks.append(norm)
        return stocks

    def set_selected_stocks(self, stocks: list[dict[str, str]]) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in stocks:
            norm = self._normalize_stock_item(item)
            if not norm or norm["symbol"] in seen:
                continue
            seen.add(norm["symbol"])
            cleaned.append(norm)
        payload = {"stocks": cleaned}
        with self.selected_stocks_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        return cleaned

    def list_board_catalog(self, board_type: str, query: str = "", limit: int = 200) -> list[dict[str, Any]]:
        return self.mac.list_board_catalog(board_type=board_type, query=query, limit=limit)

    def _resolve_watchlist(self) -> list[str]:
        """Deprecated: stocks now use page-selected list."""
        return [s["symbol"] for s in self.get_selected_stocks()]

    def refresh_once(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._refresh_once_impl()
        finally:
            self._refresh_lock.release()

    def _refresh_once_impl(self) -> None:
        try:
            self.reload_config()
            board_type = str(self.config.get("board_type") or "HY")
            board_count = int(self.config.get("board_count") or 12)
            selected = self.get_selected_boards()
            session = trading_session_status()
            trade_date = session["tradeDate"]
            sample_intraday = should_sample_intraday(session)

            if selected:
                self.mac._refresh_meta_cache()
                sectors = self.mac.fetch_board_summaries_by_codes(selected)
                sector_mode = "selected"
            else:
                sectors = self.mac.fetch_board_summaries_universe(
                    board_type=board_type,
                    count=board_count,
                )
                sector_mode = "auto"

            sector_ids = [str(s["id"]) for s in sectors if s.get("id")]

            if sample_intraday:
                for sec in sectors:
                    sid = str(sec.get("id") or "")
                    if not sid:
                        continue
                    if self.intraday.is_bulk_archived_sector_series(trade_date, sid):
                        self.intraday.delete_sector_series(trade_date, sid)
                    main_net = float(sec.get("cum_main") or sec.get("main_net_amount") or 0)
                    price = sec.get("price")
                    change_pct = sec.get("change_pct")
                    self.intraday.append_sector_snapshot(
                        trade_date,
                        sid,
                        session["currentMinute"],
                        main_net,
                        price=float(price) if price is not None else None,
                        change_pct=float(change_pct) if change_pct is not None else None,
                    )
            elif session.get("marketStatus") == "closed" and session.get("isTradingDay"):
                for sec in sectors:
                    sid = str(sec.get("id") or "")
                    if not sid:
                        continue
                    if self.intraday.is_bulk_archived_sector_series(trade_date, sid):
                        self.intraday.delete_sector_series(trade_date, sid)
                    main_net = float(sec.get("cum_main") or sec.get("main_net_amount") or 0)
                    price = sec.get("price")
                    change_pct = sec.get("change_pct")
                    self.intraday.append_sector_snapshot(
                        trade_date,
                        sid,
                        "15:00",
                        main_net,
                        price=float(price) if price is not None else None,
                        change_pct=float(change_pct) if change_pct is not None else None,
                    )

            sector_view_date = self.resolve_sector_view_date(sector_ids=sector_ids)
            sector_flows = self.build_sector_flows_for_date(
                sector_view_date,
                sector_ids,
                live_sectors=sectors,
            )
            if sector_view_date != trade_date:
                for sec in sectors:
                    flow = sector_flows.get(sec["id"]) or []
                    if not flow:
                        continue
                    last = flow[-1]
                    sec["cum_main"] = last.get("cum_main")
                    sec["cum_net"] = last.get("cum_main")
                    if last.get("change_pct") is not None:
                        sec["change_pct"] = last.get("change_pct")
                    if last.get("price") is not None:
                        sec["price"] = last.get("price")

            selected_stocks = self.get_selected_stocks()
            symbols = [s["symbol"] for s in selected_stocks]
            stock_mode = "selected" if selected_stocks else "empty"
            quotes = {q["symbol"]: q for q in self.client.quotes(symbols)} if symbols else {}

            thresholds = {
                **(self.snapshot.get("thresholds") or {}),
                **(self.config.get("order_thresholds") or {}),
            }

            stock_flows: dict[str, list] = {}
            stock_main_nets: dict[str, float] = {}
            stock_names: dict[str, str] = {}
            if symbols:
                self.client.ensure()
            for sym in symbols[:20]:
                try:
                    market, code = split_symbol(sym)
                    stock_names[sym] = self.mac.fetch_stock_name(market, code)
                    main_net = self.mac.fetch_stock_main_net(market, code)
                    stock_main_nets[sym] = main_net
                    if sample_intraday:
                        q = quotes.get(sym) or {}
                        price = float(q.get("price") or 0) if q.get("price") is not None else None
                        change_pct = q.get("change_pct")
                        self.intraday.append_snapshot(
                            trade_date,
                            sym,
                            session["currentMinute"],
                            main_net,
                            price=price if price else None,
                            change_pct=float(change_pct) if change_pct is not None else None,
                        )
                except Exception:
                    stock_main_nets[sym] = 0.0
                    stock_names[sym] = sym

            if sample_intraday:
                self.intraday.prune_old_dates(self.intraday_retention_days)

            stock_view_date = self.resolve_stock_view_date()
            stock_flows = self.build_stock_flows_for_date(
                stock_view_date,
                symbols[:20],
                live_quotes=quotes,
                live_main_nets=stock_main_nets,
            )

            if sector_view_date == trade_date or stock_view_date == trade_date:
                self._archive_today_flows_if_closed(
                    trade_date,
                    sector_view_date,
                    stock_view_date,
                    sector_flows,
                    stock_flows,
                )

            watch_rows = []
            for item in selected_stocks:
                sym = item["symbol"]
                q = quotes.get(sym)
                flow = stock_flows.get(sym) or []
                last = flow[-1] if flow else {}
                cum_tick = float(last.get("cum_main") or 0.0)
                cum_mac = float(stock_main_nets.get(sym) or 0.0)
                if stock_view_date != trade_date and flow:
                    cum_mac = cum_tick
                if not q and last.get("price") is not None:
                    q = {
                        "price": last.get("price"),
                        "change_pct": last.get("change_pct"),
                    }
                watch_rows.append(
                    {
                        "symbol": sym,
                        "name": stock_names.get(sym) or item.get("name") or sym,
                        "quote": q,
                        "cum_main": cum_mac if cum_mac else cum_tick,
                        "cum_net": cum_mac if cum_mac else cum_tick,
                        "cum_tick": cum_tick,
                        "cum_mac": cum_mac,
                        "flow_source": "intraday_sample" if flow else ("tdx_mac" if cum_mac else "tick_estimate"),
                    }
                )

            host = self.mac.host_label
            if not host and self.client.host:
                host = f"{self.client.host[0]}:{self.client.host[1]} (pytdx)"

            with self.lock:
                self.snapshot = {
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "error": None,
                    "watchlist": watch_rows,
                    "sectors": sectors,
                    "quotes": quotes,
                    "stock_flows": stock_flows,
                    "sector_flows": sector_flows,
                    "minutes": {},
                    "disclaimer": DISCLAIMER,
                    "thresholds": thresholds,
                    "tdx_root": str(self.tdx_root),
                    "host": host,
                    "data_source": "tdx_mac",
                    "board_type": board_type,
                    "sector_mode": sector_mode,
                    "selected_boards": selected,
                    "stock_mode": stock_mode,
                    "selected_stocks": selected_stocks,
                    "stock_view_date": stock_view_date,
                    "stock_intraday_dates": self.list_stock_intraday_dates(),
                    "sector_view_date": sector_view_date,
                    "sector_intraday_dates": self.list_sector_intraday_dates(sector_ids),
                    "intraday_retention_days": self.intraday_retention_days,
                    "trading_session": session,
                }
        except Exception as exc:
            with self.lock:
                self.snapshot = {
                    **self.snapshot,
                    "error": str(exc),
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_once()
            self._stop.wait(self.refresh_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="board-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.client.close()
        self.mac.close()

    def get_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self.snapshot

    def get_sector_members(self, sector_id: str) -> list[dict[str, Any]]:
        sec = next((s for s in self.get_snapshot().get("sectors") or [] if s.get("id") == sector_id), None)
        if not sec or sec.get("source") != "tdx_mac":
            return []
        return self.mac.fetch_board_members(sector_id, limit=30)
