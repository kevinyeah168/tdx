from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from workbench.domain import DataQuality, FundFlow, Membership, SectorMinute, StockMinute, TierPoint


class SectorAggregator:
    """Build sector minute records by summing the fund-flow tiers of their constituents."""

    def __init__(self, memberships: Iterable[Membership]) -> None:
        self._sector_ids_by_symbol: dict[str, tuple[str, ...]] = {}
        sector_ids_by_symbol: dict[str, set[str]] = defaultdict(set)
        for membership in memberships:
            sector_ids_by_symbol[membership.symbol].add(membership.sector_id)
        for symbol, sector_ids in sector_ids_by_symbol.items():
            self._sector_ids_by_symbol[symbol] = tuple(sorted(sector_ids))

    def aggregate(self, stocks: Iterable[StockMinute]) -> list[SectorMinute]:
        records = list(stocks)
        if not records:
            return []

        self._validate_batch_identity(records)
        observed_at = max(stock.observed_at for stock in records)
        first = records[0]
        constituents_by_sector: dict[str, list[StockMinute]] = defaultdict(list)
        for stock in records:
            for sector_id in self._sector_ids_by_symbol.get(stock.symbol, ()):
                constituents_by_sector[sector_id].append(stock)

        return [
            SectorMinute(
                trade_date=first.trade_date,
                minute=first.minute,
                sector_id=sector_id,
                change_pct=sum(stock.change_pct for stock in constituents) / len(constituents),
                member_count=len(constituents),
                funds=self._sum_funds(constituents),
                observed_at=observed_at,
                batch_id=first.batch_id,
            )
            for sector_id, constituents in sorted(constituents_by_sector.items())
        ]

    @staticmethod
    def _validate_batch_identity(stocks: list[StockMinute]) -> None:
        first = stocks[0]
        if any(
            stock.trade_date != first.trade_date
            or stock.minute != first.minute
            or stock.batch_id != first.batch_id
            for stock in stocks[1:]
        ):
            raise ValueError("stocks must share the same trade_date, minute, and batch_id")

    @staticmethod
    def _sum_funds(stocks: list[StockMinute]) -> FundFlow:
        def tier(name: str) -> TierPoint:
            return TierPoint(
                delta=sum(getattr(stock.funds, name).delta for stock in stocks),
                cumulative=sum(getattr(stock.funds, name).cumulative for stock in stocks),
                source="constituent_sum",
                quality=DataQuality.AGGREGATED,
            )

        return FundFlow(
            main=tier("main"),
            super=tier("super"),
            large=tier("large"),
            medium=tier("medium"),
            small=tier("small"),
        )
