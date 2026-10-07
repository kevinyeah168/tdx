from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from workbench.config import WorkbenchSettings
from workbench.providers.eastmoney.limit_up import EastMoneyLimitUpProvider, EastMoneyLimitUpRow
from workbench.storage.limit_up_snapshot_store import LimitUpSnapshotStore

CACHE_TTL_SECONDS = 60


class LimitUpLadderItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: str
    code: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    board_days: int
    first_seal_time: str | None = None
    last_seal_time: str | None = None
    seal_amount: float | None = None
    broken_count: int | None = None
    industry: str | None = None
    turnover_rate: float | None = None
    limit_stats: str | None = None


class LimitUpLadderTier(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    board_days: int
    label: str
    count: int
    items: list[LimitUpLadderItem] = Field(default_factory=list)


class LimitUpLadderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    limit_up_count: int = 0
    max_board: int = 0
    broken_count: int = 0
    break_rate_pct: float | None = None
    first_board_count: int = 0
    multi_board_count: int = 0


class LimitUpLadderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trade_date: str
    fetched_at: str
    source: str = "eastmoney"
    data_kind: Literal["live", "snapshot"] = "live"
    summary: LimitUpLadderSummary
    tiers: list[LimitUpLadderTier] = Field(default_factory=list)


class _CacheEntry:
    __slots__ = ("expires_at", "payload")

    def __init__(self, payload: LimitUpLadderResponse, ttl: float) -> None:
        self.payload = payload
        self.expires_at = time.monotonic() + ttl


class LimitUpLadderService:
    def __init__(
        self,
        *,
        provider: EastMoneyLimitUpProvider | None = None,
        snapshot_store: LimitUpSnapshotStore | None = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._provider = provider or EastMoneyLimitUpProvider()
        self._snapshot_store = snapshot_store
        self._cache_ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def bind_settings(self, settings: WorkbenchSettings) -> None:
        if self._snapshot_store is None:
            path = settings.data_dir / "meta" / "limit_up_snapshots.sqlite"
            self._snapshot_store = LimitUpSnapshotStore(path)
            self._snapshot_store.initialize()

    def ladder(self, trade_date: str, *, force: bool = False) -> LimitUpLadderResponse:
        normalized_date = _normalize_iso_date(trade_date)
        today = date.today().isoformat()
        is_today = normalized_date == today

        if not force:
            if is_today:
                cached = self._get_memory_cache(normalized_date)
                if cached is not None:
                    return cached
            else:
                snapshot = self._read_snapshot(normalized_date)
                if snapshot is not None:
                    return snapshot

        payload = self._fetch_and_build(normalized_date, data_kind="live" if is_today else "snapshot")
        self._save_snapshot(payload)
        self._set_memory_cache(normalized_date, payload)
        return payload

    def _fetch_and_build(self, trade_date: str, *, data_kind: Literal["live", "snapshot"]) -> LimitUpLadderResponse:
        limit_up_rows = self._provider.fetch_limit_up_pool(trade_date)
        broken_rows = self._provider.fetch_broken_pool(trade_date)
        fetched_at = _utc_now_iso()
        tiers = _build_tiers(limit_up_rows)
        summary = _build_summary(limit_up_rows, broken_rows)
        return LimitUpLadderResponse(
            trade_date=trade_date,
            fetched_at=fetched_at,
            data_kind=data_kind,
            summary=summary,
            tiers=tiers,
        )

    def _read_snapshot(self, trade_date: str) -> LimitUpLadderResponse | None:
        if self._snapshot_store is None:
            return None
        payload = self._snapshot_store.get(trade_date)
        if payload is None:
            return None
        payload = dict(payload)
        payload["data_kind"] = "snapshot"
        return LimitUpLadderResponse.model_validate(payload)

    def _save_snapshot(self, payload: LimitUpLadderResponse) -> None:
        if self._snapshot_store is None:
            return
        self._snapshot_store.save(
            payload.trade_date,
            payload.model_dump(mode="json"),
            fetched_at=payload.fetched_at,
        )

    def _get_memory_cache(self, trade_date: str) -> LimitUpLadderResponse | None:
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(trade_date)
            if entry and entry.expires_at > now:
                return entry.payload
        return None

    def _set_memory_cache(self, trade_date: str, payload: LimitUpLadderResponse) -> None:
        with self._lock:
            self._cache[trade_date] = _CacheEntry(payload, self._cache_ttl)


_default_service: LimitUpLadderService | None = None
_service_lock = threading.Lock()


def get_limit_up_ladder_service() -> LimitUpLadderService:
    global _default_service
    if _default_service is not None:
        return _default_service
    with _service_lock:
        if _default_service is None:
            _default_service = LimitUpLadderService()
    return _default_service


def _build_tiers(rows: list[EastMoneyLimitUpRow]) -> list[LimitUpLadderTier]:
    grouped: dict[int, list[LimitUpLadderItem]] = {}
    for row in rows:
        board_days = max(row.board_days, 1)
        bucket = 7 if board_days >= 7 else board_days
        grouped.setdefault(bucket, []).append(_to_item(row))

    tiers: list[LimitUpLadderTier] = []
    for board_days in sorted(grouped, reverse=True):
        items = grouped[board_days]
        items.sort(
            key=lambda item: (
                -item.board_days,
                item.first_seal_time or "99:99",
                item.code,
            ),
        )
        tiers.append(
            LimitUpLadderTier(
                board_days=board_days,
                label=_tier_label(board_days),
                count=len(items),
                items=items,
            )
        )
    return tiers


def _build_summary(
    limit_up_rows: list[EastMoneyLimitUpRow],
    broken_rows: list[EastMoneyLimitUpRow],
) -> LimitUpLadderSummary:
    limit_up_count = len(limit_up_rows)
    broken_count = len(broken_rows)
    board_days = [max(row.board_days, 1) for row in limit_up_rows]
    max_board = max(board_days) if board_days else 0
    first_board_count = sum(1 for value in board_days if value == 1)
    multi_board_count = limit_up_count - first_board_count
    denominator = limit_up_count + broken_count
    break_rate_pct = round(broken_count / denominator * 100, 1) if denominator else None
    return LimitUpLadderSummary(
        limit_up_count=limit_up_count,
        max_board=max_board,
        broken_count=broken_count,
        break_rate_pct=break_rate_pct,
        first_board_count=first_board_count,
        multi_board_count=multi_board_count,
    )


def _to_item(row: EastMoneyLimitUpRow) -> LimitUpLadderItem:
    return LimitUpLadderItem(
        symbol=row.symbol,
        code=row.code,
        name=row.name,
        price=row.price,
        change_pct=row.change_pct,
        board_days=max(row.board_days, 1),
        first_seal_time=row.first_seal_time,
        last_seal_time=row.last_seal_time,
        seal_amount=row.seal_amount,
        broken_count=row.broken_count,
        industry=row.industry,
        turnover_rate=row.turnover_rate,
        limit_stats=row.limit_stats,
    )


def _tier_label(board_days: int) -> str:
    if board_days >= 7:
        return "7板及以上"
    if board_days == 1:
        return "首板"
    return f"{board_days}板"


def _normalize_iso_date(trade_date: str) -> str:
    normalized = trade_date.strip()
    if len(normalized) == 8 and normalized.isdigit():
        return f"{normalized[0:4]}-{normalized[4:6]}-{normalized[6:8]}"
    datetime.strptime(normalized, "%Y-%m-%d")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
