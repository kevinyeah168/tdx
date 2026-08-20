from __future__ import annotations

from datetime import date, datetime, time

from workbench.domain import (
    DataQuality,
    FundFlow,
    Membership,
    ProviderMinuteBatch,
    Sector,
    Security,
    StockMinute,
)
from workbench.providers.base import MarketCatalog


class FakeMarketProvider:
    def __init__(
        self,
        stock_count: int,
        sector_count: int,
        members_per_sector: int,
    ) -> None:
        for name, value in {
            "stock_count": stock_count,
            "sector_count": sector_count,
            "members_per_sector": members_per_sector,
        }.items():
            if type(value) is not int:
                raise ValueError(f"{name} must be an integer")
        if stock_count < 1:
            raise ValueError("stock_count must be at least 1")
        if sector_count < 0:
            raise ValueError("sector_count must be nonnegative")
        if members_per_sector < 0:
            raise ValueError("members_per_sector must be nonnegative")
        if sector_count and members_per_sector > stock_count:
            raise ValueError("members_per_sector cannot exceed stock_count when sectors exist")
        self.stock_count = stock_count
        self.sector_count = sector_count
        self.members_per_sector = members_per_sector
        self._securities = [self._security(index) for index in range(stock_count)]

    @staticmethod
    def _security(index: int) -> Security:
        market_index = index % 3
        serial = index // 3
        if market_index == 0:
            market, code = "SH", f"{600000 + serial:06d}"
        elif market_index == 1:
            market, code = "SZ", f"{1 + serial:06d}"
        else:
            market, code = "BJ", f"{920000 + serial:06d}"
        return Security(
            symbol=f"{market}{code}",
            code=code,
            name=f"测试股票{index:04d}",
            market=market,
        )

    def catalog(self) -> MarketCatalog:
        sectors = [
            Sector(
                sector_id=f"{880000 + index:06d}",
                name=f"测试板块{index:03d}",
                sector_type="industry" if index % 2 == 0 else "concept",
            )
            for index in range(self.sector_count)
        ]
        memberships = [
            Membership(
                sector_id=sector.sector_id,
                symbol=self._securities[
                    (sector_index * self.members_per_sector + offset) % self.stock_count
                ].symbol,
            )
            for sector_index, sector in enumerate(sectors)
            for offset in range(self.members_per_sector)
        ]
        return MarketCatalog(
            securities=[security.model_copy(deep=True) for security in self._securities],
            sectors=sectors,
            memberships=memberships,
            version="fake-v1",
        )

    def minute_batch(self, trade_date: date, minute: str) -> ProviderMinuteBatch:
        minute_number = int(minute[:2]) * 60 + int(minute[3:])
        cumulative_factor = max(1, minute_number - 569)
        observed_at = datetime.combine(trade_date, time.fromisoformat(minute))
        batch_id = f"{trade_date.isoformat()}T{minute}"
        stocks: list[StockMinute] = []
        for index, security in enumerate(self._securities):
            direction = -1.0 if index % 3 == 0 else 1.0
            super_delta = direction * float((index % 17) * 10_000 + minute_number)
            large_delta = direction * float((index % 11) * 5_000 + minute_number)
            medium_delta = direction * float((index % 7) * 2_000)
            small_delta = direction * float((index % 5) * 1_000)
            stocks.append(
                StockMinute(
                    trade_date=trade_date,
                    minute=minute,
                    symbol=security.symbol,
                    close=round(5.0 + (index % 1000) / 100.0, 2),
                    change_pct=round(((index % 21) - 10) / 10.0, 2),
                    amount_delta=float(100_000 + index * 100),
                    funds=FundFlow.from_tiers(
                        super_delta=super_delta,
                        super_cum=super_delta * cumulative_factor,
                        large_delta=large_delta,
                        large_cum=large_delta * cumulative_factor,
                        medium_delta=medium_delta,
                        medium_cum=medium_delta * cumulative_factor,
                        small_delta=small_delta,
                        small_cum=small_delta * cumulative_factor,
                        source="fake_provider",
                        quality=DataQuality.ESTIMATED,
                    ),
                    observed_at=observed_at,
                    batch_id=batch_id,
                )
            )
        return ProviderMinuteBatch(
            trade_date=trade_date,
            minute=minute,
            stocks=stocks,
            expected_stocks=self.stock_count,
        )
