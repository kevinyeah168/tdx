from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .api_compat import DaACompatAPI
from .service import BoardService
from .trading_session import public_trading_session_payload

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config.yaml"
DIST_TDX_WEB = ROOT.parent / "tdx-web-mobile" / "dist"
DIST = DIST_TDX_WEB if DIST_TDX_WEB.exists() else ROOT / "frontend" / "dist"

app = FastAPI(title="TDX Local Board", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = BoardService(CONFIG)
compat = DaACompatAPI(service)


@app.on_event("startup")
def _startup() -> None:
    service.refresh_once()
    service.start()
    compat.sync_default_sectors_from_config()
    compat.sync_default_stocks_from_config()


@app.on_event("shutdown")
def _shutdown() -> None:
    service.stop()


@app.get("/api/health")
def health():
    snap = service.get_snapshot()
    return {"ok": True, "updated_at": snap.get("updated_at"), "error": snap.get("error")}


def _align_field(flow_rows: list, timeline: list[str], field: str) -> list:
    by_t = {str(r["time"]): float(r.get(field) or 0) for r in flow_rows}
    values = []
    last = None
    for t in timeline:
        if t in by_t:
            last = by_t[t]
        values.append(last)
    return values


def _build_sector_curves(snap: dict) -> dict:
    """Align sector main-force cumulative series onto a shared minute timeline."""
    sectors = snap.get("sectors") or []
    flows = snap.get("sector_flows") or {}
    preserve_order = snap.get("sector_mode") == "selected"
    time_set: set[str] = set()
    for sec in sectors:
        for row in flows.get(sec["id"]) or []:
            t = row.get("time")
            if t:
                time_set.add(str(t))
    timeline = sorted(time_set)
    series = []
    for sec in sectors:
        rows = flows.get(sec["id"]) or []
        main_values = _align_field(rows, timeline, "cum_main")
        last_flow = rows[-1] if rows else {}
        change_pct = sec.get("change_pct")
        if last_flow.get("change_pct") is not None:
            change_pct = last_flow.get("change_pct")
        series.append(
            {
                "id": sec["id"],
                "name": sec["name"],
                "change_pct": change_pct,
                "cum_net": sec.get("cum_main") or sec.get("cum_net") or 0,
                "cum_main": sec.get("cum_main") or 0,
                "cum_super": sec.get("cum_super") or 0,
                "cum_large": sec.get("cum_large") or 0,
                "cum_medium": sec.get("cum_medium") or 0,
                "cum_small": sec.get("cum_small") or 0,
                "source": sec.get("source"),
                "values": main_values,
                "tier_series": {
                    "main": main_values,
                    "super": _align_field(rows, timeline, "cum_super"),
                    "large": _align_field(rows, timeline, "cum_large"),
                    "medium": _align_field(rows, timeline, "cum_medium"),
                    "small": _align_field(rows, timeline, "cum_small"),
                },
            }
        )
    if not preserve_order:
        series.sort(key=lambda s: float(s.get("cum_main") or 0), reverse=True)
    return {"timeline": timeline, "series": series}


def _build_stock_curves(snap: dict) -> dict:
    """Align watchlist stock main-force cumulative series onto a shared minute timeline."""
    watchlist = snap.get("watchlist") or []
    stock_flows = snap.get("stock_flows") or {}
    time_set: set[str] = set()
    for row in watchlist:
        sym = row.get("symbol")
        if not sym:
            continue
        for pt in stock_flows.get(sym) or []:
            t = pt.get("time")
            if t:
                time_set.add(str(t))
    timeline = sorted(time_set)
    series = []
    for row in watchlist:
        sym = row.get("symbol")
        if not sym:
            continue
        flow_rows = stock_flows.get(sym) or []
        main_values = _align_field(flow_rows, timeline, "cum_main")
        quote = row.get("quote") or {}
        last_flow = flow_rows[-1] if flow_rows else {}
        change_pct = quote.get("change_pct") if quote else last_flow.get("change_pct")
        price = quote.get("price") if quote else last_flow.get("price")
        series.append(
            {
                "id": sym,
                "symbol": sym,
                "name": row.get("name") or sym,
                "change_pct": change_pct,
                "price": price,
                "cum_main": row.get("cum_mac") or row.get("cum_main") or row.get("cum_net") or 0,
                "cum_tick": row.get("cum_tick") or 0,
                "cum_mac": row.get("cum_mac") or 0,
                "flow_source": row.get("flow_source") or "intraday_sample",
                "values": main_values,
            }
        )
    preserve_order = snap.get("stock_mode") == "selected"
    if preserve_order:
        order = {row.get("symbol"): idx for idx, row in enumerate(watchlist) if row.get("symbol")}
        series.sort(key=lambda s: order.get(s.get("id"), 9999))
    else:
        series.sort(key=lambda s: float(s.get("cum_main") or 0), reverse=True)
    return {"timeline": timeline, "series": series}


def _patch_snap_stock_date(snap: dict, trade_date: str) -> dict:
    symbols = [s["symbol"] for s in snap.get("selected_stocks") or []]
    if not symbols:
        return snap
    flows = service.build_stock_flows_for_date(trade_date, symbols)
    watchlist = []
    name_map = {w.get("symbol"): w.get("name") for w in snap.get("watchlist") or []}
    for sym in symbols:
        flow = flows.get(sym) or []
        rows = service.intraday.load_stock_series(trade_date, sym)
        last_row = rows[-1] if rows else {}
        last_flow = flow[-1] if flow else {}
        cum = float(last_flow.get("cum_main") or last_row.get("main_net") or 0)
        q = None
        if last_row.get("price") is not None:
            q = {
                "price": last_row.get("price"),
                "change_pct": last_row.get("change_pct"),
            }
        watchlist.append(
            {
                "symbol": sym,
                "name": name_map.get(sym) or sym,
                "quote": q,
                "cum_main": cum,
                "cum_net": cum,
                "cum_tick": cum,
                "cum_mac": cum,
                "flow_source": "intraday_sample" if flow else "none",
            }
        )
    out = dict(snap)
    out["watchlist"] = watchlist
    out["stock_flows"] = flows
    out["stock_view_date"] = trade_date
    return out


def _patch_snap_sector_date(snap: dict, trade_date: str) -> dict:
    sector_ids = [str(s.get("id")) for s in snap.get("sectors") or [] if s.get("id")]
    if not sector_ids:
        return snap
    flows = service.build_sector_flows_for_date(trade_date, sector_ids)
    sectors = []
    name_map = {str(s.get("id")): s for s in snap.get("sectors") or []}
    for sid in sector_ids:
        prev = name_map.get(sid) or {"id": sid, "name": sid}
        flow = flows.get(sid) or []
        rows = service.intraday.load_sector_series(trade_date, sid)
        last_row = rows[-1] if rows else {}
        last_flow = flow[-1] if flow else {}
        cum = float(last_flow.get("cum_main") or last_row.get("main_net") or 0)
        sec = dict(prev)
        sec["cum_main"] = cum
        sec["cum_net"] = cum
        if last_row.get("change_pct") is not None:
            sec["change_pct"] = last_row.get("change_pct")
        elif last_flow.get("change_pct") is not None:
            sec["change_pct"] = last_flow.get("change_pct")
        if last_row.get("price") is not None:
            sec["price"] = last_row.get("price")
        sectors.append(sec)
    out = dict(snap)
    out["sectors"] = sectors
    out["sector_flows"] = flows
    out["sector_view_date"] = trade_date
    return out


class BoardItem(BaseModel):
    id: str
    name: str = ""


class SelectedBoardsPayload(BaseModel):
    boards: list[BoardItem] = Field(default_factory=list)


class SelectedStocksPayload(BaseModel):
    stocks: list[BoardItem] = Field(default_factory=list)


@app.get("/api/board-catalog")
def board_catalog(type: str = "HY", q: str = "", limit: int = 200):
    return {
        "boards": service.list_board_catalog(board_type=type, query=q, limit=limit),
        "type": type,
    }


@app.get("/api/selected-boards")
def get_selected_boards():
    boards = service.get_selected_boards()
    return {"boards": boards, "mode": "selected" if boards else "auto"}


@app.post("/api/selected-boards")
def save_selected_boards(payload: SelectedBoardsPayload):
    boards = service.set_selected_boards([b.model_dump() for b in payload.boards])
    service.refresh_once()
    return {"ok": True, "boards": boards, "updated_at": service.get_snapshot().get("updated_at")}


@app.get("/api/stock-catalog")
def stock_catalog(q: str = "", limit: int = 50):
    data = compat.catalog.search(q, page=1, page_size=min(max(limit, 1), 100))
    snap = service.get_snapshot()
    quotes = snap.get("quotes") or {}
    stocks = []
    for row in data.get("stocks") or []:
        sym = str(row.get("symbol") or "")
        if not sym:
            continue
        quote = quotes.get(sym) or {}
        stocks.append(
            {
                "id": sym,
                "symbol": sym,
                "name": row.get("displayName") or sym,
                "change_pct": quote.get("change_pct"),
            }
        )
    return {"stocks": stocks, "total": data.get("total", 0)}


@app.get("/api/selected-stocks")
def get_selected_stocks():
    stocks = service.get_selected_stocks()
    return {
        "stocks": [{"id": s["symbol"], "name": s["name"]} for s in stocks],
        "mode": "selected" if stocks else "empty",
    }


@app.post("/api/selected-stocks")
def save_selected_stocks(payload: SelectedStocksPayload):
    stocks = service.set_selected_stocks([{"symbol": s.id, "name": s.name} for s in payload.stocks])
    service.refresh_once()
    return {"ok": True, "stocks": [{"id": s["symbol"], "name": s["name"]} for s in stocks], "updated_at": service.get_snapshot().get("updated_at")}


@app.get("/api/board")
def board(stock_date: str | None = None, sector_date: str | None = None):
    snap = service.get_snapshot()
    stock_view = stock_date or snap.get("stock_view_date") or service.resolve_stock_view_date()
    sector_ids = [str(s.get("id")) for s in snap.get("sectors") or [] if s.get("id")]
    sector_view = sector_date or snap.get("sector_view_date") or service.resolve_sector_view_date(
        sector_ids=sector_ids,
    )
    if stock_date and stock_date != snap.get("stock_view_date"):
        snap = _patch_snap_stock_date(snap, stock_date)
        stock_view = stock_date
    if sector_date and sector_date != snap.get("sector_view_date"):
        snap = _patch_snap_sector_date(snap, sector_date)
        sector_view = sector_date
    curves = _build_sector_curves(snap)
    stock_curves = _build_stock_curves(snap)
    return {
        "updated_at": snap.get("updated_at"),
        "error": snap.get("error"),
        "disclaimer": snap.get("disclaimer"),
        "tdx_root": snap.get("tdx_root"),
        "host": snap.get("host"),
        "watchlist": snap.get("watchlist") or [],
        "sectors": snap.get("sectors") or [],
        "timeline": curves["timeline"],
        "sector_series": curves["series"],
        "stock_timeline": stock_curves["timeline"],
        "stock_series": stock_curves["series"],
        "board_type": snap.get("board_type"),
        "sector_mode": snap.get("sector_mode"),
        "selected_boards": snap.get("selected_boards") or [],
        "stock_mode": snap.get("stock_mode"),
        "selected_stocks": snap.get("selected_stocks") or [],
        "stock_view_date": stock_view,
        "sector_view_date": sector_view,
        "stock_intraday_dates": snap.get("stock_intraday_dates") or service.list_stock_intraday_dates(),
        "sector_intraday_dates": snap.get("sector_intraday_dates") or service.list_sector_intraday_dates(
            sector_ids,
        ),
        "intraday_retention_days": snap.get("intraday_retention_days") or service.intraday_retention_days,
        "trading_session": snap.get("trading_session"),
    }


@app.get("/api/sector-intraday/dates")
def sector_intraday_dates():
    session = public_trading_session_payload()
    snap = service.get_snapshot()
    sector_ids = [str(s.get("id")) for s in snap.get("sectors") or [] if s.get("id")]
    return {
        "dates": service.list_sector_intraday_dates(sector_ids),
        "tradeDate": session["tradeDate"],
        "retention_days": service.intraday_retention_days,
    }


@app.get("/api/stock-intraday/dates")
def stock_intraday_dates():
    session = public_trading_session_payload()
    return {
        "dates": service.list_stock_intraday_dates(),
        "tradeDate": session["tradeDate"],
        "retention_days": service.intraday_retention_days,
    }


@app.get("/api/stock/{symbol}/intraday")
def stock_intraday(symbol: str, date: str | None = None):
    sym = symbol.upper().replace(".", "")
    trade_date = date or service.resolve_stock_view_date()
    rows = service.intraday.load_stock_series(trade_date, sym)
    if not rows:
        raise HTTPException(404, f"暂无 {sym} 在 {trade_date} 的采样数据")
    return service.get_stock_intraday_detail(sym, trade_date)


@app.get("/api/stock/{symbol}")
def stock_detail(symbol: str, date: str | None = None):
    sym = symbol.upper().replace(".", "")
    if date:
        rows = service.intraday.load_stock_series(date, sym)
        if rows:
            return service.get_stock_intraday_detail(sym, date)
    snap = service.get_snapshot()
    quote = (snap.get("quotes") or {}).get(sym)
    flow = (snap.get("stock_flows") or {}).get(sym) or []
    if not quote and not flow:
        raise HTTPException(404, f"暂无该标的缓存，请将其加入自选个股: {sym}")
    return {
        "symbol": sym,
        "trade_date": snap.get("stock_view_date"),
        "quote": quote,
        "minutes": (snap.get("minutes") or {}).get(sym) or [],
        "fund_flow": flow,
        "disclaimer": snap.get("disclaimer"),
        "updated_at": snap.get("updated_at"),
    }


@app.get("/api/sector/{sector_id}")
def sector_detail(sector_id: str):
    snap = service.get_snapshot()
    sectors = snap.get("sectors") or []
    sec = next((s for s in sectors if s.get("id") == sector_id or s.get("name") == sector_id), None)
    if not sec:
        raise HTTPException(404, "板块不存在")
    members = service.get_sector_members(sec["id"])
    if not members and sec.get("codes"):
        quotes = snap.get("quotes") or {}
        for code in sec.get("codes") or []:
            q = quotes.get(code)
            flow = (snap.get("stock_flows") or {}).get(code) or []
            members.append(
                {
                    "symbol": code,
                    "quote": q,
                    "cum_net": flow[-1].get("cum_main", 0) if flow else 0,
                }
            )
    return {
        "sector": sec,
        "members": members,
        "fund_flow": (snap.get("sector_flows") or {}).get(sec["id"]) or [],
        "disclaimer": snap.get("disclaimer"),
        "updated_at": snap.get("updated_at"),
    }


@app.post("/api/refresh")
def force_refresh():
    service.refresh_once()
    return {"ok": True, "updated_at": service.get_snapshot().get("updated_at")}


# --- daA web-mobile compatible APIs (通达信口径) ---


@app.get("/api/public/web-client-config")
def public_web_client_config():
    return compat.public_web_client_config()


@app.get("/api/public/trading-session")
def public_trading_session():
    return public_trading_session_payload()


@app.get("/api/capital-flow/dates")
@app.get("/api/public/capital-flow/dates")
def capital_flow_dates():
    return {"dates": compat.list_dates()}


@app.get("/api/public/capital-flow/latest")
def public_latest_capital_flow():
    session = public_trading_session_payload()
    return compat._build_sector_flow_snapshot(date=session["tradeDate"])


@app.get("/api/public/market-flow")
@app.get("/api/public/market-flow/latest")
def public_market_flow(date: str | None = None):
    session = public_trading_session_payload()
    trade_date = date or session["tradeDate"]
    return compat._build_market_flow(trade_date)


@app.get("/api/market-flow")
def market_flow(date: str, scope: str | None = None):
    return compat._build_market_flow(date)


@app.get("/api/member/me")
def member_me():
    return compat.member_me()


@app.get("/api/member/sector-trend")
def member_sector_trend():
    return compat.member.sector_trend_options()


class SectorTrendSavePayload(BaseModel):
    sectorIds: list[int] = Field(default_factory=list)
    customColors: dict[str, str | None] | None = None


@app.put("/api/member/sector-trend")
def save_member_sector_trend(payload: SectorTrendSavePayload):
    colors = None
    if payload.customColors:
        colors = {int(k): v for k, v in payload.customColors.items()}
    try:
        return compat.save_sector_trend(payload.sectorIds, colors)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/member/sector-search")
def member_sector_search(q: str | None = None, page: int = 1, page_size: int = 20):
    return compat.search_sectors(q or "", page=page, page_size=page_size)


@app.get("/api/member/sector-flow")
def member_sector_flow(date: str, sector_ids: str | None = None):
    ids = None
    if sector_ids:
        ids = [int(x) for x in sector_ids.split(",") if x.strip().isdigit()]
    return compat._build_sector_flow_snapshot(date=date, sector_ids=ids)


@app.get("/api/member/stocks")
def member_stocks():
    return compat.member.stock_options_payload()


class StockSavePayload(BaseModel):
    stockIds: list[int] = Field(default_factory=list)
    customColors: dict[str, str | None] | None = None


@app.put("/api/member/stocks")
def save_member_stocks(payload: StockSavePayload):
    colors = None
    if payload.customColors:
        colors = {int(k): v for k, v in payload.customColors.items()}
    try:
        return compat.save_stocks(payload.stockIds, colors)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/member/stock-options")
def member_stock_options(q: str | None = None, page: int = 1, page_size: int = 20):
    return compat.catalog.search(q or "", page=page, page_size=page_size)


@app.get("/api/member/stock-flow/dates")
def member_stock_flow_dates():
    return {"dates": compat.list_dates()}


@app.get("/api/member/stock-flow")
def member_stock_flow(date: str, stock_ids: str | None = None):
    ids = None
    if stock_ids:
        ids = [int(x) for x in stock_ids.split(",") if x.strip().isdigit()]
    return compat._build_stock_flow_snapshot(date=date, stock_ids=ids)


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")
