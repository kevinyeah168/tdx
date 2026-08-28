from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from workbench.collector.history_sync import HistorySyncService
from workbench.config import WorkbenchSettings
from workbench.domain import BarPeriod
from workbench.providers.tdx.runtime import create_real_provider
from workbench.query.stocks import StockQueryService
from workbench.storage.history_store import HistoryStore
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def get_settings(request: Request) -> WorkbenchSettings:
    settings = getattr(request.app.state, "workbench_settings", None)
    if settings is None:
        return WorkbenchSettings()
    return settings


def get_meta_store(settings: WorkbenchSettings = Depends(get_settings)) -> MetaStore:
    store = MetaStore(settings.meta_db)
    store.initialize()
    return store


def get_history_store(settings: WorkbenchSettings = Depends(get_settings)) -> HistoryStore:
    store = HistoryStore(settings.data_dir / "history" / "bars.sqlite")
    store.initialize()
    return store


def _sync_bars_for_symbol(settings: WorkbenchSettings, symbol: str, count: int) -> None:
    provider = create_real_provider(settings)
    try:
        HistorySyncService(provider, settings).sync_symbols([symbol], count=count)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def _try_sync_bars(settings: WorkbenchSettings, symbol: str, count: int, *, timeout_seconds: float = 8.0) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_sync_bars_for_symbol, settings, symbol, count)
        try:
            future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            future.cancel()


def get_hot_store(
    trade_date: date = Query(alias="date"),
    settings: WorkbenchSettings = Depends(get_settings),
) -> HotStore:
    path = settings.hot_db_for(trade_date.isoformat())
    if not path.is_file():
        raise HTTPException(status_code=404, detail="fund-flow data not found")
    store = HotStore(path)
    store.initialize()
    return store


def create_stock_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])

    @router.get("/{symbol}")
    def stock_detail(symbol: str, meta: MetaStore = Depends(get_meta_store)) -> dict[str, object]:
        payload = StockQueryService(meta).security(symbol)
        if payload is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        return payload

    @router.get("/{symbol}/sectors")
    def stock_sectors(symbol: str, meta: MetaStore = Depends(get_meta_store)) -> dict[str, object]:
        if StockQueryService(meta).security(symbol) is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        snapshot = meta.catalog_snapshot()
        return {
            "symbol": symbol.upper(),
            "items": StockQueryService(meta).sectors_for(symbol),
            "metadata": {
                "catalog_version": snapshot.catalog_version,
                "stale": snapshot.stale,
                "source": snapshot.source,
            },
        }

    @router.get("/{symbol}/intraday")
    def stock_intraday(
        symbol: str,
        trade_date: date = Query(alias="date"),
        meta: MetaStore = Depends(get_meta_store),
        hot: HotStore = Depends(get_hot_store),
    ) -> dict[str, object]:
        if StockQueryService(meta).security(symbol) is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        points = StockQueryService(meta, hot).intraday(symbol, trade_date.isoformat())
        if not points:
            raise HTTPException(status_code=404, detail="intraday data not found")
        snapshot = meta.catalog_snapshot()
        return {
            "symbol": symbol.upper(),
            "trade_date": trade_date.isoformat(),
            "points": points,
            "metadata": {
                "catalog_version": snapshot.catalog_version,
                "stale": snapshot.stale,
                "source": snapshot.source,
            },
        }

    @router.get("/{symbol}/bars")
    def stock_bars(
        symbol: str,
        period: BarPeriod = Query(default="day"),
        count: int = Query(default=120, ge=1, le=800),
        meta: MetaStore = Depends(get_meta_store),
        history: HistoryStore = Depends(get_history_store),
        settings: WorkbenchSettings = Depends(get_settings),
    ) -> dict[str, object]:
        if StockQueryService(meta).security(symbol) is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        bars, gap_reason = StockQueryService(meta, history=history).bars(symbol, period, count)
        if not bars:
            try:
                _try_sync_bars(settings, symbol.upper(), count)
                bars, gap_reason = StockQueryService(meta, history=history).bars(symbol, period, count)
            except Exception:
                pass
        if not bars:
            raise HTTPException(status_code=404, detail=gap_reason or "bars not found")
        snapshot = meta.catalog_snapshot()
        return {
            "symbol": symbol.upper(),
            "period": period,
            "bars": bars,
            "metadata": {
                "catalog_version": snapshot.catalog_version,
                "stale": snapshot.stale,
                "source": snapshot.source,
            },
        }

    @router.get("/{symbol}/order-book")
    def stock_order_book(symbol: str, meta: MetaStore = Depends(get_meta_store)) -> dict[str, object]:
        if StockQueryService(meta).security(symbol) is None:
            raise HTTPException(status_code=404, detail="symbol not found")
        snapshot = meta.catalog_snapshot()
        return {
            "symbol": symbol.upper(),
            "quality": "gap",
            "gap_reason": "order book snapshot not collected",
            "metadata": {
                "catalog_version": snapshot.catalog_version,
                "stale": snapshot.stale,
                "source": snapshot.source,
            },
        }

    return router
