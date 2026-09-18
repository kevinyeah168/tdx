from __future__ import annotations

from collections import defaultdict
from math import fsum
from typing import Iterable

from workbench.domain import DataQuality, Membership, SectorGrayMinute, StockGrayMinute

SECTOR_GRAY_SOURCE = "constituent_sum:eastmoney:graymarket:darktrade"


class SectorGrayAggregator:
    """Sum constituent stock gray-flow snapshots into sector gray minutes."""

    def __init__(self, memberships: Iterable[Membership]) -> None:
        symbols_by_sector: dict[str, set[str]] = defaultdict(set)
        for membership in memberships:
            symbols_by_sector[membership.sector_id].add(membership.symbol.upper())
        self._symbols_by_sector = {
            sector_id: tuple(sorted(symbols))
            for sector_id, symbols in symbols_by_sector.items()
        }

    def aggregate(
        self,
        stock_gray: list[StockGrayMinute],
        *,
        trade_date,
        minute: str,
        observed_at,
        batch_id: str,
    ) -> list[SectorGrayMinute]:
        if not stock_gray:
            return []

        gray_by_symbol = {record.symbol.upper(): record for record in stock_gray}
        records: list[SectorGrayMinute] = []
        for sector_id in sorted(self._symbols_by_sector):
            members = self._symbols_by_sector[sector_id]
            covered = [symbol for symbol in members if symbol in gray_by_symbol]
            if not covered:
                continue
            records.append(
                SectorGrayMinute(
                    trade_date=trade_date,
                    minute=minute,
                    sector_id=sector_id,
                    member_count=len(members),
                    gray_covered_count=len(covered),
                    open_cum=fsum(gray_by_symbol[symbol].open_cum for symbol in covered),
                    dark_cum=fsum(gray_by_symbol[symbol].dark_cum for symbol in covered),
                    total_cum=fsum(gray_by_symbol[symbol].total_cum for symbol in covered),
                    observed_at=observed_at,
                    batch_id=batch_id,
                    source=SECTOR_GRAY_SOURCE,
                    quality=DataQuality.AGGREGATED,
                )
            )
        return records
