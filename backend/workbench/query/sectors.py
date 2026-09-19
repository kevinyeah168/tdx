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
    SectorSnapshotItem,
    SectorSnapshotResponse,
    SectorSummary,
)
from workbench.providers.tdx.sector_float_cap import build_symbol_free_float_cap_details
from workbench.providers.tdx.text_clean import clean_tdx_text
from workbench.query.custom_sector_flow import CustomSectorFlowService
from workbench.query.custom_sector_ids import CUSTOM_SECTOR_TYPE, is_custom_sector_id
from workbench.services.custom_sectors import CustomSectorService
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

    def _resolve_member_symbols(self, sector_id: str) -> list[str]:
        if is_custom_sector_id(sector_id):
            return CustomSectorService(self._meta).symbols_for(sector_id)
        return self._meta.memberships_for(sector_id)

    def _rank_members_from_hot(
        self,
        symbols: list[str],
        *,
        trade_date: str,
        minute: str,
        limit: int,
    ) -> tuple[str, list[tuple[str, float, float]]]:
        if not symbols:
            return minute, []
        effective_minute = minute
        rows: list[tuple[str, float, float]] = []
        with self._hot.connect(readonly=True) as connection:  # type: ignore[union-attr]
            for candidate in (
                minute,
                self._hot.latest_stock_minute(trade_date),  # type: ignore[union-attr]
                self._hot.latest_complete_minute(trade_date),  # type: ignore[union-attr]
            ):
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
        return effective_minute, [(str(row[0]), float(row[1]), float(row[2])) for row in rows]

    def list_sectors(
        self,
        *,
        query: str | None = None,
        limit: int | None = None,
    ) -> SectorListResponse:
        snapshot = self._meta.catalog_snapshot()
        normalized_query = str(query or "").strip()
        effective_limit = None if limit is None else max(1, min(int(limit), 1500))
        sql = (
            "SELECT s.sector_id, s.name, s.sector_type, COUNT(m.symbol) "
            "FROM sector_master s "
            "LEFT JOIN sector_membership m ON m.sector_id = s.sector_id "
        )
        params: list[object] = []
        if normalized_query:
            like = f"%{normalized_query}%"
            sql += "WHERE s.name LIKE ? OR s.sector_id LIKE ? "
            params.extend([like, like])
        sql += "GROUP BY s.sector_id, s.name, s.sector_type ORDER BY s.sector_id"
        if effective_limit is not None:
            sql += " LIMIT ?"
            params.append(effective_limit)
        with self._meta.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        items = [
            SectorSummary(
                sector_id=row[0],
                name=row[1],
                sector_type=row[2],
                member_count=int(row[3]),
            )
            for row in rows
        ]
        custom_query = normalized_query.lower()
        for sector in CustomSectorService(self._meta).list_sectors():
            if custom_query:
                if custom_query not in sector.name.lower() and custom_query not in sector.sector_id.lower():
                    continue
            items.append(
                SectorSummary(
                    sector_id=sector.sector_id,
                    name=sector.name,
                    sector_type=CUSTOM_SECTOR_TYPE,
                    member_count=len(sector.symbols),
                )
            )
        if effective_limit is not None:
            items = items[:effective_limit]
        return SectorListResponse(
            items=items,
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

    def sector_snapshot(
        self,
        sector_ids: list[str],
        *,
        trade_date: str,
        minute: str,
    ) -> SectorSnapshotResponse:
        if self._hot is None:
            raise ValueError("hot store is required for sector snapshot")
        snapshot = self._meta.catalog_snapshot()
        unique_ids = list(dict.fromkeys(sector_id.strip() for sector_id in sector_ids if sector_id.strip()))
        if not unique_ids:
            return SectorSnapshotResponse(
                trade_date=trade_date,
                minute=minute,
                items=[],
                metadata=QueryMetadata(
                    catalog_version=snapshot.catalog_version,
                    stale=snapshot.stale,
                    source=snapshot.source,
                ),
            )

        effective_minute = minute
        items: list[SectorSnapshotItem] = []
        custom_flow = CustomSectorFlowService(self._meta, self._hot)
        for sector_id in unique_ids:
            if is_custom_sector_id(sector_id):
                tip = custom_flow.fund_tip_at_minute(trade_date, sector_id, minute)
            else:
                tip = self._hot.sector_fund_tip(trade_date, sector_id, minute)
            if tip is None:
                continue
            effective_minute = str(tip["minute"])
            items.append(
                SectorSnapshotItem(
                    sector_id=sector_id,
                    main_cumulative=float(tip["main_cum"]),
                    change_pct=float(tip.get("change_pct") or 0.0),
                )
            )

        return SectorSnapshotResponse(
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
        limit: int = 60,
        live_members: list[dict[str, object]] | None = None,
        quote_client: object | None = None,
    ) -> SectorMemberRankResponse:
        if self._hot is None:
            raise ValueError("hot store is required for member ranking")
        snapshot = self._meta.catalog_snapshot()
        symbols = self._resolve_member_symbols(sector_id)
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

        effective_minute, hot_rows = self._rank_members_from_hot(
            symbols,
            trade_date=trade_date,
            minute=minute,
            limit=limit,
        )
        if hot_rows:
            ranked_symbols = [symbol for symbol, _, _ in hot_rows]
            names = self._security_names(ranked_symbols)
            symbol_caps = (
                build_symbol_free_float_cap_details(quote_client, ranked_symbols)
                if quote_client is not None
                else {}
            )
            items = [
                self._member_rank_item(
                    symbol=symbol,
                    name=names.get(symbol, symbol),
                    main_cum=main_cum,
                    change_pct=change_pct,
                    free_cap=symbol_caps[symbol].live if symbol in symbol_caps else None,
                    free_cap_avg=symbol_caps[symbol].avg if symbol in symbol_caps else None,
                )
                for symbol, main_cum, change_pct in hot_rows
            ]
            return SectorMemberRankResponse(
                sector_id=sector_id,
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

        if live_members:
            ranked = sorted(
                live_members,
                key=lambda item: (-float(item["main_cumulative"]), str(item["symbol"])),
            )[:limit]
            ranked_symbols = [str(item["symbol"]) for item in ranked]
            names = self._security_names(ranked_symbols)
            symbol_caps = (
                build_symbol_free_float_cap_details(quote_client, ranked_symbols)
                if quote_client is not None
                else {}
            )
            items = [
                self._member_rank_item(
                    symbol=str(item["symbol"]),
                    name=clean_tdx_text(
                        names.get(str(item["symbol"]))
                        or item.get("name")
                        or item["symbol"],
                        fallback=str(item["symbol"]),
                    ),
                    main_cum=float(item["main_cumulative"]),
                    change_pct=float(item.get("change_pct") or 0.0),
                    free_cap=(
                        symbol_caps[str(item["symbol"])].live
                        if str(item["symbol"]) in symbol_caps
                        else None
                    ),
                    free_cap_avg=(
                        symbol_caps[str(item["symbol"])].avg
                        if str(item["symbol"]) in symbol_caps
                        else None
                    ),
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

    @staticmethod
    def _member_rank_item(
        *,
        symbol: str,
        name: str,
        main_cum: float,
        change_pct: float,
        free_cap: float | None,
        free_cap_avg: float | None = None,
    ) -> SectorMemberRankItem:
        ratio = None
        if free_cap is not None and free_cap > 0:
            ratio = round(main_cum / free_cap * 100.0, 4)
        ratio_avg = None
        if free_cap_avg is not None and free_cap_avg > 0:
            ratio_avg = round(main_cum / free_cap_avg * 100.0, 4)
        return SectorMemberRankItem(
            symbol=symbol,
            name=name,
            main_cumulative=main_cum,
            change_pct=change_pct,
            free_float_market_cap=free_cap if free_cap else None,
            main_net_ratio=ratio,
            free_float_market_cap_avg=free_cap_avg if free_cap_avg else None,
            main_net_ratio_avg=ratio_avg,
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
        symbols = self._resolve_member_symbols(sector_id)
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
        return {
            str(row[0]): clean_tdx_text(row[1], fallback=str(row[0]))
            for row in rows
        }
