from __future__ import annotations

from workbench.query.models import (
    QueryMetadata,
    SectorBreadthCounts,
    SectorBreadthResponse,
    SectorListResponse,
    SectorMemberRankItem,
    SectorMemberRankResponse,
    SectorRankItem,
    SectorRankResponse,
    SectorSummary,
)
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


def _is_limit_up(change_pct: float) -> bool:
    if change_pct <= 0:
        return False
    if change_pct >= 19.5:
        return True
    if change_pct >= 9.9:
        return True
    return 4.9 <= change_pct <= 5.2


def _is_limit_down(change_pct: float) -> bool:
    if change_pct >= 0:
        return False
    if change_pct <= -19.5:
        return True
    if change_pct <= -9.9:
        return True
    return -5.2 <= change_pct <= -4.9


class SectorQueryService:
    def __init__(self, meta: MetaStore, hot: HotStore | None = None) -> None:
        self._meta = meta
        self._hot = hot

    def _resolve_member_symbols(self, sector_id: str, *, limit: int) -> list[str]:
        symbols = self._meta.memberships_for(sector_id)
        if symbols:
            return symbols[: limit * 3]
        return []

    def list_sectors(self) -> SectorListResponse:
        snapshot = self._meta.catalog_snapshot()
        with self._meta.connect() as connection:
            rows = connection.execute(
                "SELECT s.sector_id, s.name, s.sector_type, COUNT(m.symbol) "
                "FROM sector_master s "
                "LEFT JOIN sector_membership m ON m.sector_id = s.sector_id "
                "GROUP BY s.sector_id, s.name, s.sector_type "
                "ORDER BY s.sector_id"
            ).fetchall()
        return SectorListResponse(
            items=[
                SectorSummary(
                    sector_id=row[0],
                    name=row[1],
                    sector_type=row[2],
                    member_count=int(row[3]),
                )
                for row in rows
            ],
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
            ),
        )

    def sector_ranking(
        self,
        *,
        trade_date: str,
        minute: str | None = None,
        limit: int = 12,
    ) -> SectorRankResponse:
        if self._hot is None:
            raise ValueError("hot store is required for sector ranking")
        snapshot = self._meta.catalog_snapshot()
        effective_minute = minute or self._hot.latest_sector_minute(trade_date) or self._hot.latest_complete_minute(trade_date)
        if not effective_minute:
            return SectorRankResponse(
                trade_date=trade_date,
                minute="",
                items=[],
                metadata=QueryMetadata(
                    catalog_version=snapshot.catalog_version,
                    stale=snapshot.stale,
                    source=snapshot.source,
                ),
            )

        sector_names: dict[str, tuple[str, str]] = {}
        with self._meta.connect() as connection:
            rows = connection.execute(
                "SELECT sector_id, name, sector_type FROM sector_master"
            ).fetchall()
        for row in rows:
            sector_names[str(row[0])] = (str(row[1]), str(row[2]))

        with self._hot.connect(readonly=True) as connection:
            rank_rows = connection.execute(
                """
                SELECT sector.sector_id, sector.main_cum, sector.change_pct
                FROM sector_minute AS sector
                WHERE sector.trade_date = ?
                    AND sector.minute = ?
                ORDER BY sector.main_cum DESC, sector.sector_id
                LIMIT ?
                """,
                (trade_date, effective_minute, limit),
            ).fetchall()

        items: list[SectorRankItem] = []
        for row in rank_rows:
            sector_id = str(row[0])
            name, sector_type = sector_names.get(sector_id, (sector_id, "unknown"))
            items.append(
                SectorRankItem(
                    sector_id=sector_id,
                    name=name,
                    sector_type=sector_type,
                    main_cumulative=float(row[1]),
                    change_pct=float(row[2]),
                )
            )

        return SectorRankResponse(
            trade_date=trade_date,
            minute=effective_minute,
            items=items,
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
                batch_id=f"{trade_date}T{effective_minute}",
            ),
        )

    def member_ranking(
        self,
        sector_id: str,
        *,
        trade_date: str,
        minute: str,
        limit: int = 20,
        live_members: list[dict[str, object]] | None = None,
    ) -> SectorMemberRankResponse:
        if self._hot is None:
            raise ValueError("hot store is required for member ranking")
        snapshot = self._meta.catalog_snapshot()
        symbols = self._resolve_member_symbols(sector_id, limit=limit)
        if live_members:
            symbols = list(dict.fromkeys([*symbols, *[str(item["symbol"]) for item in live_members]]))
        if not symbols and not live_members:
            return SectorMemberRankResponse(
                sector_id=sector_id,
                trade_date=trade_date,
                minute=minute,
                items=[],
                metadata=QueryMetadata(
                    catalog_version=snapshot.catalog_version,
                    stale=snapshot.stale,
                    source=snapshot.source,
                ),
            )
        if live_members:
            ranked = sorted(
                live_members,
                key=lambda item: (-float(item["main_cumulative"]), str(item["symbol"])),
            )[:limit]
            names = self._security_names([str(item["symbol"]) for item in ranked])
            items = [
                SectorMemberRankItem(
                    symbol=str(item["symbol"]),
                    name=str(item.get("name") or names.get(str(item["symbol"]), str(item["symbol"]))),
                    main_cumulative=float(item["main_cumulative"]),
                    change_pct=float(item.get("change_pct") or 0.0),
                )
                for item in ranked
            ]
            return SectorMemberRankResponse(
                sector_id=sector_id,
                trade_date=trade_date,
                minute=minute,
                items=items,
                metadata=QueryMetadata(
                    catalog_version=snapshot.catalog_version,
                    stale=snapshot.stale,
                    source="tdx.live.members",
                    batch_id=f"{trade_date}T{minute}-live",
                ),
            )

        names = self._security_names(symbols)
        effective_minute = minute
        rows = []
        if symbols:
            with self._hot.connect(readonly=True) as connection:
                for candidate in (minute, self._hot.latest_stock_minute(trade_date), self._hot.latest_complete_minute(trade_date)):
                    if not candidate:
                        continue
                    placeholders = ",".join("?" for _ in symbols)
                    rows = connection.execute(
                        f"""
                        SELECT stock.symbol, stock.main_cum, stock.change_pct
                        FROM stock_minute AS stock
                        WHERE stock.trade_date = ?
                            AND stock.minute = ?
                            AND stock.symbol IN ({placeholders})
                        ORDER BY stock.main_cum DESC, stock.symbol
                        LIMIT ?
                        """,
                        (trade_date, candidate, *symbols, limit),
                    ).fetchall()
                    if rows:
                        effective_minute = str(candidate)
                        break
        items = [
            SectorMemberRankItem(
                symbol=str(row[0]),
                name=names.get(str(row[0]), str(row[0])),
                main_cumulative=float(row[1]),
                change_pct=float(row[2]),
            )
            for row in rows
        ]
        if not items and live_members:
            effective_minute = minute
            items = [
                SectorMemberRankItem(
                    symbol=str(item["symbol"]),
                    name=str(item.get("name") or item["symbol"]),
                    main_cumulative=float(item["main_cumulative"]),
                    change_pct=float(item.get("change_pct") or 0.0),
                )
                for item in live_members[:limit]
            ]
        return SectorMemberRankResponse(
            sector_id=sector_id,
            trade_date=trade_date,
            minute=effective_minute,
            items=items,
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source if items else "tdx.live.members",
                batch_id=f"{trade_date}T{effective_minute}" if items else None,
            ),
        )

    def member_breadth(
        self,
        sector_id: str,
        *,
        trade_date: str,
        minute: str,
    ) -> SectorBreadthResponse:
        if self._hot is None:
            raise ValueError("hot store is required for member breadth")
        snapshot = self._meta.catalog_snapshot()
        symbols = self._meta.memberships_for(sector_id)
        empty_counts = SectorBreadthCounts(
            limit_up=0,
            limit_down=0,
            up=0,
            down=0,
            flat=0,
            sampled=0,
            total_members=len(symbols),
        )
        if not symbols:
            return SectorBreadthResponse(
                sector_id=sector_id,
                trade_date=trade_date,
                minute=minute,
                counts=empty_counts,
                limit_up=[],
                limit_down=[],
                up=[],
                down=[],
                metadata=QueryMetadata(
                    catalog_version=snapshot.catalog_version,
                    stale=snapshot.stale,
                    source=snapshot.source,
                ),
            )
        names = self._security_names(symbols)
        with self._hot.connect(readonly=True) as connection:
            placeholders = ",".join("?" for _ in symbols)
            rows = connection.execute(
                f"""
                SELECT stock.symbol, stock.main_cum, stock.change_pct
                FROM stock_minute AS stock
                INNER JOIN collection_status AS status
                    ON status.trade_date = stock.trade_date
                    AND status.minute = stock.minute
                    AND status.batch_id = stock.batch_id
                    AND status.status = 'complete'
                WHERE stock.trade_date = ?
                    AND stock.minute = ?
                    AND stock.symbol IN ({placeholders})
                ORDER BY stock.change_pct DESC, stock.symbol
                """,
                (trade_date, minute, *symbols),
            ).fetchall()
        items = [
            SectorMemberRankItem(
                symbol=str(row[0]),
                name=names.get(str(row[0]), str(row[0])),
                main_cumulative=float(row[1]),
                change_pct=float(row[2]),
            )
            for row in rows
        ]
        limit_up = [item for item in items if _is_limit_up(item.change_pct)]
        limit_down = [item for item in items if _is_limit_down(item.change_pct)]
        up = [item for item in items if item.change_pct > 0 and not _is_limit_up(item.change_pct)]
        down = [item for item in items if item.change_pct < 0 and not _is_limit_down(item.change_pct)]
        flat = len(items) - len(limit_up) - len(limit_down) - len(up) - len(down)
        counts = SectorBreadthCounts(
            limit_up=len(limit_up),
            limit_down=len(limit_down),
            up=len(up),
            down=len(down),
            flat=max(0, flat),
            sampled=len(items),
            total_members=len(symbols),
        )
        return SectorBreadthResponse(
            sector_id=sector_id,
            trade_date=trade_date,
            minute=minute,
            counts=counts,
            limit_up=sorted(limit_up, key=lambda item: item.change_pct, reverse=True),
            limit_down=sorted(limit_down, key=lambda item: item.change_pct),
            up=sorted(up, key=lambda item: item.change_pct, reverse=True),
            down=sorted(down, key=lambda item: item.change_pct),
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
                batch_id=f"{trade_date}T{minute}",
            ),
        )

    def _security_names(self, symbols: list[str]) -> dict[str, str]:
        if not symbols:
            return {}
        with self._meta.connect() as connection:
            placeholders = ",".join("?" for _ in symbols)
            rows = connection.execute(
                f"SELECT symbol, name FROM security_master WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}
