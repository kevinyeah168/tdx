from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from workbench.collector.trading_clock import (
    AUCTION_BOARD_DEFAULT_SORT,
    AUCTION_BOARD_SORT_KEYS,
    auction_phase_at,
)
from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.auction_board import (
    AUCTION_BOARD_RANK_LIMIT,
    EastMoneyAuctionBoardProvider,
    EastMoneyAuctionBoardRow,
    auction_fetched_at_iso,
)
from workbench.providers.eastmoney.gray_market import GrayMarketProvider
from workbench.storage.auction_snapshot_store import AuctionSnapshotStore

CACHE_TTL_SECONDS = 10
GRAY_MERGE_TTL_SECONDS = 60


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
    limit: int = AUCTION_BOARD_RANK_LIMIT
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
        limit: int = AUCTION_BOARD_RANK_LIMIT,
        force: bool = False,
    ) -> AuctionBoardResponse:
        normalized_date = _normalize_iso_date(trade_date)
        sort_key = sort if sort in AUCTION_BOARD_SORT_KEYS else AUCTION_BOARD_DEFAULT_SORT
        lim = max(1, min(int(limit), AUCTION_BOARD_RANK_LIMIT))
        today = date.today().isoformat()
        is_today = normalized_date == today
        phase = auction_phase_at() if is_today else "closed"
        cache_key = f"{normalized_date}:{sort_key}:{lim}"

        if not force:
            cached = self._get_memory_cache(cache_key)
            if cached is not None:
                return cached

        if not is_today:
            snapshot = self._read_snapshot(normalized_date, sort_key, limit=lim)
            if snapshot is not None:
                self._set_memory_cache(cache_key, snapshot, ttl=60.0)
                return snapshot
            if force:
                payload = self._fetch_live(
                    normalized_date,
                    sort_key=sort_key,
                    limit=lim,
                    phase="closed",
                )
                self._save_snapshot(normalized_date, sort_key, payload)
                snapshot = self._read_snapshot(normalized_date, sort_key, limit=lim) or payload
                self._set_memory_cache(cache_key, snapshot, ttl=60.0)
                return snapshot
            payload = AuctionBoardResponse(
                trade_date=normalized_date,
                fetched_at=_utc_now_iso(),
                data_kind="snapshot",
                phase="closed",
                sort=sort_key,
                limit=lim,
                items=[],
            )
            self._set_memory_cache(cache_key, payload, ttl=60.0)
            return payload

        if phase in {"auction", "post_auction"}:
            payload = self._fetch_live(normalized_date, sort_key=sort_key, limit=lim, phase=phase)
            self._save_snapshot(normalized_date, sort_key, payload)
            self._set_memory_cache(cache_key, payload)
            return payload

        if phase == "waiting":
            payload = AuctionBoardResponse(
                trade_date=normalized_date,
                fetched_at=_utc_now_iso(),
                data_kind="live",
                phase="waiting",
                sort=sort_key,
                limit=lim,
                items=[],
            )
            self._set_memory_cache(cache_key, payload, ttl=5.0)
            return payload

        snapshot = self._read_snapshot(normalized_date, sort_key, limit=lim)
        if snapshot is not None:
            self._set_memory_cache(cache_key, snapshot, ttl=60.0)
            return snapshot

        payload = AuctionBoardResponse(
            trade_date=normalized_date,
            fetched_at=_utc_now_iso(),
            data_kind="live",
            phase=phase,
            sort=sort_key,
            limit=lim,
            items=[],
        )
        self._set_memory_cache(cache_key, payload, ttl=30.0)
        return payload

    def _fetch_live(
        self,
        trade_date: str,
        *,
        sort_key: str,
        limit: int,
        phase: str,
    ) -> AuctionBoardResponse:
        rows, source = self._provider.fetch_rank(
            trade_date=trade_date,
            sort_key=sort_key,
            limit=limit,
            rank_side="desc",
        )
        open_map = self._open_net_inflow_map(trade_date, phase)
        items = [_to_item(index + 1, row, open_map.get(row.code)) for index, row in enumerate(rows)]
        return AuctionBoardResponse(
            trade_date=trade_date,
            fetched_at=auction_fetched_at_iso(),
            source=source,
            data_kind="live",
            phase=phase,  # type: ignore[arg-type]
            sort=sort_key,
            limit=limit,
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

    def _read_snapshot(self, trade_date: str, sort_key: str, *, limit: int) -> AuctionBoardResponse | None:
        if self._snapshot_store is None:
            return None
        raw = self._snapshot_store.get(trade_date, sort_key)
        if raw is None:
            return None
        try:
            payload = AuctionBoardResponse.model_validate(raw)
        except Exception:
            return None
        payload.data_kind = "snapshot"
        payload.phase = "closed"
        if len(payload.items) > limit:
            payload.items = payload.items[:limit]
            for index, item in enumerate(payload.items, start=1):
                item.rank = index
        payload.limit = limit
        return payload

    def _save_snapshot(self, trade_date: str, sort_key: str, payload: AuctionBoardResponse) -> None:
        if self._snapshot_store is None:
            return
        if payload.phase == "auction":
            return
        if not payload.items:
            return
        snapshot_payload = payload.model_copy(update={"data_kind": "snapshot", "phase": "closed"})
        self._snapshot_store.save(
            trade_date,
            sort_key,
            snapshot_payload.model_dump(mode="json"),
            fetched_at=payload.fetched_at,
        )

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


def _normalize_iso_date(trade_date: str) -> str:
    normalized = trade_date.strip()
    if len(normalized) == 8 and normalized.isdigit():
        return f"{normalized[0:4]}-{normalized[4:6]}-{normalized[6:8]}"
    datetime.strptime(normalized, "%Y-%m-%d")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
