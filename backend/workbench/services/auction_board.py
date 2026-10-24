from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from workbench.collector.trading_clock import (
    AUCTION_BOARD_DEFAULT_SORT,
    AUCTION_BOARD_SORT_KEYS,
    auction_phase_at,
)
from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.auction_board import (
    AUCTION_BOARD_TOP_LIMIT,
    EastMoneyAuctionBoardProvider,
    EastMoneyAuctionBoardRow,
    auction_fetched_at_iso,
)
from workbench.providers.eastmoney.gray_market import GrayMarketProvider
from workbench.storage.auction_snapshot_store import AuctionSnapshotStore

CACHE_TTL_SECONDS = 10
GRAY_MERGE_TTL_SECONDS = 60
FULL_MARKET_MIN_INTERVAL_SECONDS = 45.0
DEFAULT_PAGE_SIZE = 100


class AuctionBoardItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: int
    symbol: str
    code: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    volume_ratio: float | None = None
    amount: float | None = None
    volume: float | None = None
    open_net_inflow: float | None = None


class AuctionBoardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    fetched_at: str
    source: str = "eastmoney"
    data_kind: Literal["live", "snapshot"] = "live"
    phase: Literal["waiting", "auction", "post_auction", "closed"] = "closed"
    sort: str = AUCTION_BOARD_DEFAULT_SORT
    scope: Literal["top", "market"] = "market"
    q: str | None = None
    offset: int = 0
    limit: int = DEFAULT_PAGE_SIZE
    total: int = 0
    items: list[AuctionBoardItem] = Field(default_factory=list)


class _CacheEntry:
    __slots__ = ("expires_at", "payload")

    def __init__(self, payload: AuctionBoardResponse, ttl: float) -> None:
        self.payload = payload
        self.expires_at = time.monotonic() + ttl


class _GrayMapEntry:
    __slots__ = ("expires_at", "values")

    def __init__(self, values: dict[str, float], ttl: float) -> None:
        self.values = values
        self.expires_at = time.monotonic() + ttl


class AuctionBoardService:
    def __init__(
        self,
        *,
        provider: EastMoneyAuctionBoardProvider | None = None,
        gray_provider: GrayMarketProvider | None = None,
        snapshot_store: AuctionSnapshotStore | None = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._provider = provider or EastMoneyAuctionBoardProvider()
        self._gray_provider = gray_provider or GrayMarketProvider()
        self._snapshot_store = snapshot_store
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._gray_map: dict[str, _GrayMapEntry] = {}
        self._last_full_fetch_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def bind_settings(self, settings: WorkbenchSettings) -> None:
        if self._snapshot_store is None:
            path = settings.data_dir / "meta" / "auction_snapshots.sqlite"
            self._snapshot_store = AuctionSnapshotStore(path)
            self._snapshot_store.initialize()

    def board(
        self,
        trade_date: str,
        *,
        sort: str = AUCTION_BOARD_DEFAULT_SORT,
        scope: Literal["top", "market"] = "market",
        q: str | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        force: bool = False,
    ) -> AuctionBoardResponse:
        normalized_date = _normalize_iso_date(trade_date)
        sort_key = sort if sort in AUCTION_BOARD_SORT_KEYS else AUCTION_BOARD_DEFAULT_SORT
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(int(limit), 500))
        query_text = (q or "").strip() or None
        today = date.today().isoformat()
        is_today = normalized_date == today
        phase = auction_phase_at() if is_today else "closed"
        cache_key = (
            f"{normalized_date}:{sort_key}:{scope}:{query_text or ''}:"
            f"{safe_offset}:{safe_limit}"
        )

        if not force:
            cached = self._get_memory_cache(cache_key)
            if cached is not None:
                return cached

        use_live_top = scope == "top" and is_today and phase in {"auction", "post_auction"}
        if use_live_top:
            payload = self._fetch_top_live(
                normalized_date,
                sort_key=sort_key,
                phase=phase,
                offset=safe_offset,
                limit=safe_limit,
                q=query_text,
            )
            cache_ttl = 3.0 if not payload.items else None
            self._set_memory_cache(cache_key, payload, ttl=cache_ttl)
            return payload

        if scope == "top" and is_today and phase == "waiting":
            payload = _empty_response(
                normalized_date,
                sort_key=sort_key,
                scope="top",
                q=query_text,
                offset=safe_offset,
                limit=safe_limit,
                phase="waiting",
            )
            self._set_memory_cache(cache_key, payload, ttl=5.0)
            return payload

        payload = self._board_from_snapshot(
            normalized_date,
            sort_key=sort_key,
            scope=scope,
            q=query_text,
            offset=safe_offset,
            limit=safe_limit,
            phase=phase if is_today else "closed",
            data_kind="snapshot" if not is_today or phase == "closed" else "live",
            force=force,
        )
        cache_ttl = 60.0 if payload.data_kind == "snapshot" else None
        self._set_memory_cache(cache_key, payload, ttl=cache_ttl)
        return payload

    def collect_full_market(self, trade_date: str, *, force: bool = True) -> AuctionBoardResponse:
        normalized_date = _normalize_iso_date(trade_date)
        today = date.today().isoformat()
        phase = auction_phase_at() if normalized_date == today else "closed"
        self._refresh_full_market(
            normalized_date,
            sort_key=AUCTION_BOARD_DEFAULT_SORT,
            phase=phase,
            force=force,
        )
        stored = self._read_market_rows(
            normalized_date,
            sort_key=AUCTION_BOARD_DEFAULT_SORT,
            q=None,
            offset=0,
            limit=DEFAULT_PAGE_SIZE,
            phase=phase,
            data_kind="snapshot" if phase == "closed" else "live",
        )
        return stored or _empty_response(
            normalized_date,
            sort_key=AUCTION_BOARD_DEFAULT_SORT,
            scope="market",
            q=None,
            offset=0,
            limit=DEFAULT_PAGE_SIZE,
            phase=phase,
        )

    def _board_from_snapshot(
        self,
        trade_date: str,
        *,
        sort_key: str,
        scope: Literal["top", "market"],
        q: str | None,
        offset: int,
        limit: int,
        phase: str,
        data_kind: Literal["live", "snapshot"],
        force: bool,
    ) -> AuctionBoardResponse:
        if phase in {"auction", "post_auction"}:
            should_refresh = force or (
                self._snapshot_store is not None
                and not self._snapshot_store.has_stock_rows(trade_date)
            )
            if should_refresh or self._should_refresh_full_market(trade_date):
                self._refresh_full_market(
                    trade_date,
                    sort_key=sort_key,
                    phase=phase,
                    force=force,
                )

        read_offset = offset
        read_limit = limit
        if scope == "top":
            if offset >= AUCTION_BOARD_TOP_LIMIT:
                return _empty_response(
                    trade_date,
                    sort_key=sort_key,
                    scope="top",
                    q=q,
                    offset=offset,
                    limit=limit,
                    phase=phase,
                    data_kind=data_kind,
                )
            read_limit = min(limit, AUCTION_BOARD_TOP_LIMIT - offset)

        stored = self._read_market_rows(
            trade_date,
            sort_key=sort_key,
            q=q,
            offset=read_offset,
            limit=read_limit,
            phase=phase,
            data_kind=data_kind,
            scope=scope,
        )
        if stored is not None and stored.total > 0:
            if scope == "top":
                stored.total = min(stored.total, AUCTION_BOARD_TOP_LIMIT)
            return stored

        if force and phase == "closed":
            self._refresh_full_market(
                trade_date,
                sort_key=sort_key,
                phase="closed",
                force=True,
            )
            stored = self._read_market_rows(
                trade_date,
                sort_key=sort_key,
                q=q,
                offset=read_offset,
                limit=read_limit,
                phase="closed",
                data_kind="snapshot",
                scope=scope,
            )
            if stored is not None and stored.total > 0:
                if scope == "top":
                    stored.total = min(stored.total, AUCTION_BOARD_TOP_LIMIT)
                return stored

        return _empty_response(
            trade_date,
            sort_key=sort_key,
            scope=scope,
            q=q,
            offset=offset,
            limit=limit,
            phase=phase,
            data_kind=data_kind,
        )

    def _fetch_top_live(
        self,
        trade_date: str,
        *,
        sort_key: str,
        phase: str,
        offset: int,
        limit: int,
        q: str | None,
    ) -> AuctionBoardResponse:
        fetch_limit = min(AUCTION_BOARD_TOP_LIMIT, offset + limit)
        rows, source = self._provider.fetch_rank(
            trade_date=trade_date,
            sort_key=sort_key,
            limit=fetch_limit,
            rank_side="desc",
        )
        open_map = self._open_net_inflow_map(trade_date, phase)
        items = [
            _to_item(index + 1, row, open_map.get(row.code))
            for index, row in enumerate(rows)
        ]
        if q:
            query = q.lower()
            items = [
                item
                for item in items
                if query in item.code.lower() or query in item.name.lower()
            ]
        total = len(items)
        page_items = items[offset : offset + limit]
        for index, item in enumerate(page_items, start=offset + 1):
            item.rank = index
        return AuctionBoardResponse(
            trade_date=trade_date,
            fetched_at=auction_fetched_at_iso(),
            source=source,
            data_kind="live",
            phase=phase,  # type: ignore[arg-type]
            sort=sort_key,
            scope="top",
            q=q,
            offset=offset,
            limit=limit,
            total=total,
            items=page_items,
        )

    def _refresh_full_market(
        self,
        trade_date: str,
        *,
        sort_key: str,
        phase: str,
        force: bool,
    ) -> None:
        if self._snapshot_store is None:
            return
        if phase in {"waiting", "closed"} and not force:
            return
        if phase == "auction" and not force and not self._should_refresh_full_market(trade_date):
            return
        try:
            rows, source = self._provider.fetch_all_market(
                trade_date=trade_date,
                sort_key=sort_key,
            )
        except Exception:
            return
        if not rows:
            return
        open_map = self._open_net_inflow_map(trade_date, phase)
        payload_rows = [_row_to_store_dict(row, open_map.get(row.code)) for row in rows]
        fetched_at = auction_fetched_at_iso()
        self._snapshot_store.replace_stock_rows(
            trade_date,
            payload_rows,
            fetched_at=fetched_at,
            source=source,
        )
        with self._lock:
            self._last_full_fetch_at[trade_date] = time.monotonic()

    def _should_refresh_full_market(self, trade_date: str) -> bool:
        with self._lock:
            last_at = self._last_full_fetch_at.get(trade_date)
        if last_at is None:
            return True
        return time.monotonic() - last_at >= FULL_MARKET_MIN_INTERVAL_SECONDS

    def _read_market_rows(
        self,
        trade_date: str,
        *,
        sort_key: str,
        q: str | None,
        offset: int,
        limit: int,
        phase: str,
        data_kind: Literal["live", "snapshot"] = "snapshot",
        scope: Literal["top", "market"] = "market",
    ) -> AuctionBoardResponse | None:
        if self._snapshot_store is None:
            return None
        if not self._snapshot_store.has_stock_rows(trade_date):
            return None
        meta = self._snapshot_store.get_day_meta(trade_date) or {}
        raw_items, total = self._snapshot_store.query_stock_rows(
            trade_date,
            sort=sort_key,
            q=q,
            offset=offset,
            limit=limit,
        )
        items = [
            AuctionBoardItem(
                rank=offset + index + 1,
                symbol=str(row["symbol"]),
                code=str(row["code"]),
                name=str(row["name"]),
                price=_optional_float(row.get("price")),
                change_pct=_optional_float(row.get("change_pct")),
                volume_ratio=_optional_float(row.get("volume_ratio")),
                amount=_optional_float(row.get("amount")),
                volume=_optional_float(row.get("volume")),
                open_net_inflow=_optional_float(row.get("open_net_inflow")),
            )
            for index, row in enumerate(raw_items)
        ]
        return AuctionBoardResponse(
            trade_date=trade_date,
            fetched_at=str(meta.get("fetched_at") or _utc_now_iso()),
            source=str(meta.get("source") or "eastmoney"),
            data_kind=data_kind,
            phase=phase,  # type: ignore[arg-type]
            sort=sort_key,
            scope=scope,
            q=q,
            offset=offset,
            limit=limit,
            total=total,
            items=items,
        )

    def _open_net_inflow_map(self, trade_date: str, phase: str) -> dict[str, float]:
        if phase not in {"auction", "post_auction"}:
            return {}
        with self._lock:
            cached = self._gray_map.get(trade_date)
            if cached is not None and time.monotonic() < cached.expires_at:
                return cached.values
        try:
            samples = self._gray_provider.fetch_full_market_gray_snapshots(trade_date=trade_date)
            values = {sample.code: sample.open_net_inflow for sample in samples}
        except Exception:
            return {}
        with self._lock:
            self._gray_map[trade_date] = _GrayMapEntry(values, GRAY_MERGE_TTL_SECONDS)
        return values

    def _get_memory_cache(self, cache_key: str) -> AuctionBoardResponse | None:
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None or time.monotonic() >= entry.expires_at:
                return None
            return entry.payload

    def _set_memory_cache(self, cache_key: str, payload: AuctionBoardResponse, ttl: float | None = None) -> None:
        with self._lock:
            self._cache[cache_key] = _CacheEntry(payload, ttl if ttl is not None else self._cache_ttl)


_default_service: AuctionBoardService | None = None
_service_lock = threading.Lock()


def get_auction_board_service() -> AuctionBoardService:
    global _default_service
    if _default_service is not None:
        return _default_service
    with _service_lock:
        if _default_service is None:
            _default_service = AuctionBoardService()
    return _default_service


def _to_item(rank: int, row: EastMoneyAuctionBoardRow, open_net_inflow: float | None) -> AuctionBoardItem:
    resolved_inflow = row.open_net_inflow if row.open_net_inflow is not None else open_net_inflow
    return AuctionBoardItem(
        rank=rank,
        symbol=row.symbol,
        code=row.code,
        name=row.name,
        price=row.price,
        change_pct=row.change_pct,
        volume_ratio=row.volume_ratio,
        amount=row.amount,
        volume=row.volume,
        open_net_inflow=resolved_inflow,
    )


def _row_to_store_dict(row: EastMoneyAuctionBoardRow, open_net_inflow: float | None) -> dict[str, Any]:
    resolved_inflow = row.open_net_inflow if row.open_net_inflow is not None else open_net_inflow
    return {
        "symbol": row.symbol,
        "code": row.code,
        "name": row.name,
        "price": row.price,
        "change_pct": row.change_pct,
        "volume_ratio": row.volume_ratio,
        "amount": row.amount,
        "volume": row.volume,
        "open_net_inflow": resolved_inflow,
    }


def _empty_response(
    trade_date: str,
    *,
    sort_key: str,
    scope: Literal["top", "market"],
    q: str | None,
    offset: int,
    limit: int,
    phase: str,
    data_kind: Literal["live", "snapshot"] = "live",
) -> AuctionBoardResponse:
    return AuctionBoardResponse(
        trade_date=trade_date,
        fetched_at=_utc_now_iso(),
        data_kind=data_kind,
        phase=phase,  # type: ignore[arg-type]
        sort=sort_key,
        scope=scope,
        q=q,
        offset=offset,
        limit=limit,
        total=0,
        items=[],
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_iso_date(trade_date: str) -> str:
    normalized = trade_date.strip()
    if len(normalized) == 8 and normalized.isdigit():
        return f"{normalized[0:4]}-{normalized[4:6]}-{normalized[6:8]}"
    datetime.strptime(normalized, "%Y-%m-%d")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
