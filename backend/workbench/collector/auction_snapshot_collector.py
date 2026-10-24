"""Persist East Money auction-board snapshots during the 09:25–09:30 post-auction window."""

from __future__ import annotations

from datetime import date, datetime

from workbench.collector.trading_clock import auction_phase_at
from workbench.config import WorkbenchSettings
from workbench.services.auction_board import AuctionBoardService

AUCTION_SNAPSHOT_MINUTES = frozenset({"09:26", "09:29"})


class AuctionSnapshotCollector:
    def __init__(
        self,
        settings: WorkbenchSettings,
        *,
        service: AuctionBoardService | None = None,
    ) -> None:
        self._settings = settings
        self._service = service or AuctionBoardService()
        self._service.bind_settings(settings)
        self._completed: set[str] = set()

    def collect_if_due(self, trade_date: date, now: datetime) -> dict[str, object] | None:
        if auction_phase_at(now) != "post_auction":
            return None
        minute = now.strftime("%H:%M")
        if minute not in AUCTION_SNAPSHOT_MINUTES:
            return None
        key = f"{trade_date.isoformat()}:{minute}"
        if key in self._completed:
            return None
        self._completed.add(key)

        payload = self._service.collect_full_market(trade_date.isoformat(), force=True)
        return {
            "mode": "auction-snapshot",
            "trade_date": trade_date.isoformat(),
            "minute": minute,
            "total": payload.total,
            "source": payload.source,
        }
