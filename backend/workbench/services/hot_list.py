from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from workbench.config import WorkbenchSettings
from workbench.domain import DataQuality
from workbench.providers.eastmoney.hot_rank import EastMoneyHotRankProvider
from workbench.providers.tdx.quotes import TdxQuoteService, normalize_quote_batch
from workbench.providers.tonghuashun.hot_rank import TonghuashunHotRankProvider
from workbench.storage.meta_store import MetaStore

StockBoard = Literal["popularity", "surge"]
StockSource = Literal["eastmoney", "ths", "both"]
BoardType = Literal["concept", "industry"]

# Aligned with frontend HOT_LIST_POLL_MS; third-party APIs are rate-sensitive.
CACHE_TTL_SECONDS = 60


class HotStockItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: int
    symbol: str
    code: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    rank_change: int | None = None
    hot_value: float | None = None
    source: str


class HotStockListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    board: StockBoard
    source: StockSource
    fetched_at: str
    items: list[HotStockItem] = Field(default_factory=list)
    eastmoney: list[HotStockItem] | None = None
    ths: list[HotStockItem] | None = None


class HotBoardItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: int
    board_code: str
    name: str
    change_pct: float | None = None
    hot_value: float | None = None
    rank_change: int | None = None
    source: str = "ths"


class HotBoardListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    board_type: BoardType
    fetched_at: str
    source: str = "ths"
    items: list[HotBoardItem] = Field(default_factory=list)


class _CacheEntry:
    __slots__ = ("expires_at", "payload")

    def __init__(self, payload, ttl: float) -> None:
        self.payload = payload
        self.expires_at = time.monotonic() + ttl


class HotListService:
    def __init__(
        self,
        *,
        eastmoney: EastMoneyHotRankProvider | None = None,
        tonghuashun: TonghuashunHotRankProvider | None = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._eastmoney = eastmoney or EastMoneyHotRankProvider()
        self._tonghuashun = tonghuashun or TonghuashunHotRankProvider()
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def stock_list(
        self,
        board: StockBoard,
        source: StockSource,
        *,
        meta: MetaStore | None = None,
        settings: WorkbenchSettings | None = None,
        quote_client: object | None = None,
    ) -> HotStockListResponse:
        fetched_at = _utc_now_iso()
        if source == "both":
            eastmoney = self._cached_stock_rows("eastmoney", board)
            ths = self._cached_stock_rows("ths", board)
            ths_name_fallback = _name_fallback_from_items(ths)
            eastmoney = self._enrich_stock_items(
                eastmoney,
                meta=meta,
                settings=settings,
                quote_client=quote_client,
                board=board,
                name_fallback=ths_name_fallback,
            )
            ths = self._enrich_stock_items(
                ths,
                meta=meta,
                settings=settings,
                quote_client=quote_client,
                board=board,
            )
            return HotStockListResponse(
                board=board,
                source=source,
                fetched_at=fetched_at,
                items=[],
                eastmoney=eastmoney,
                ths=ths,
            )
        items = self._cached_stock_rows(source, board)
        items = self._enrich_stock_items(
            items,
            meta=meta,
            settings=settings,
            quote_client=quote_client,
            board=board,
        )
        return HotStockListResponse(
            board=board,
            source=source,
            fetched_at=fetched_at,
            items=items,
        )

    def board_list(self, board_type: BoardType) -> HotBoardListResponse:
        cache_key = f"board:{board_type}"
        rows = self._cached(cache_key, lambda: self._tonghuashun.fetch_board_rank(board_type))
        return HotBoardListResponse(
            board_type=board_type,
            fetched_at=_utc_now_iso(),
            items=[
                HotBoardItem(
                    rank=row.rank,
                    board_code=row.board_code,
                    name=row.name,
                    change_pct=row.change_pct,
                    hot_value=row.hot_value,
                    rank_change=row.rank_change,
                )
                for row in rows
            ],
        )

    def _cached_stock_rows(self, source: Literal["eastmoney", "ths"], board: StockBoard) -> list[HotStockItem]:
        # v2: THS rank_change merged from day-period API
        cache_key = f"stock:{source}:{board}:v2"
        if source == "eastmoney":
            rows = self._cached(cache_key, lambda: self._eastmoney.fetch_stock_rank(board))
            return [
                HotStockItem(
                    rank=row.rank,
                    symbol=row.symbol,
                    code=row.code,
                    name=row.name,
                    price=row.price,
                    change_pct=row.change_pct,
                    rank_change=row.rank_change,
                    source="eastmoney",
                )
                for row in rows
            ]
        rows = self._cached(cache_key, lambda: self._tonghuashun.fetch_stock_rank(board))
        return [
            HotStockItem(
                rank=row.rank,
                symbol=row.symbol,
                code=row.code,
                name=row.name,
                change_pct=row.change_pct,
                hot_value=row.hot_value,
                rank_change=row.rank_change,
                source="ths",
            )
            for row in rows
        ]

    def _cached(self, key: str, loader):
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry and entry.expires_at > now:
                return entry.payload
        payload = loader()
        with self._lock:
            self._cache[key] = _CacheEntry(payload, self._cache_ttl)
        return payload

    def _enrich_stock_items(
        self,
        items: list[HotStockItem],
        *,
        meta: MetaStore | None,
        settings: WorkbenchSettings | None,
        quote_client: object | None,
        board: StockBoard | None = None,
        name_fallback: dict[str, str] | None = None,
    ) -> list[HotStockItem]:
        if not items:
            return items

        symbols = [item.symbol for item in items]
        names_by_symbol = meta.security_names(symbols) if meta is not None else {}
        missing_codes = [
            item.code
            for item in items
            if _is_missing_name(item, names_by_symbol.get(item.symbol) or item.name)
        ]
        names_by_code = (
            meta.security_names_by_codes(missing_codes) if meta is not None and missing_codes else {}
        )
        fallback = dict(name_fallback or {})
        if board is not None and any(
            _is_missing_name(item, names_by_symbol.get(item.symbol) or names_by_code.get(item.code) or item.name)
            for item in items
        ):
            ths_rows = self._cached_stock_rows("ths", board)
            fallback.update(_name_fallback_from_items(ths_rows))

        quotes = self._live_quotes(symbols, settings=settings, quote_client=quote_client)

        enriched: list[HotStockItem] = []
        for item in items:
            quote = quotes.get(item.symbol, {})
            name = (
                names_by_symbol.get(item.symbol)
                or names_by_code.get(item.code)
                or fallback.get(item.symbol)
                or fallback.get(item.code)
                or item.name
            )
            enriched.append(
                item.model_copy(
                    update={
                        "name": name,
                        "price": item.price if item.price is not None else quote.get("price"),
                        "change_pct": item.change_pct if item.change_pct is not None else quote.get("change_pct"),
                    }
                )
            )
        return enriched

    @staticmethod
    def _live_quotes(
        symbols: list[str],
        *,
        settings: WorkbenchSettings | None,
        quote_client: object | None,
    ) -> dict[str, dict[str, float | None]]:
        if not symbols or settings is None or quote_client is None:
            return {}
        try:
            service = TdxQuoteService(settings=settings, enhanced_client=quote_client)
            rows = service.fetch_quote_rows(symbols)
            observed_at = datetime.now(timezone.utc)
            snapshots = normalize_quote_batch(
                rows,
                trade_date=date.today(),
                minute=observed_at.strftime("%H:%M"),
                observed_at=observed_at,
                source="tdx.enhanced.quotes",
                quality=DataQuality.OFFICIAL,
            )
        except Exception:
            return {}
        return {
            snapshot.symbol: {"price": snapshot.price, "change_pct": snapshot.change_pct}
            for snapshot in snapshots
        }


_default_service: HotListService | None = None
_service_lock = threading.Lock()


def get_hot_list_service() -> HotListService:
    global _default_service
    if _default_service is not None:
        return _default_service
    with _service_lock:
        if _default_service is None:
            _default_service = HotListService()
    return _default_service


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_missing_name(item: HotStockItem, name: str | None = None) -> bool:
    candidate = name if name is not None else item.name
    return not candidate or candidate in {item.symbol, item.code}


def _name_fallback_from_items(items: list[HotStockItem]) -> dict[str, str]:
    fallback: dict[str, str] = {}
    for item in items:
        if _is_missing_name(item):
            continue
        fallback[item.symbol] = item.name
        fallback[item.code] = item.name
    return fallback
