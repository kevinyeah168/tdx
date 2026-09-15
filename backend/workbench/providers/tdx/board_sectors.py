from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

from easy_tdx import MacClient
from easy_tdx.config import get_port
from easy_tdx.mac.enums import BoardType
from easy_tdx.transport.sync import MAC_HOSTS

from workbench.config import WorkbenchSettings
from workbench.domain import DataQuality, FundFlow, Sector, SectorMinute, TierPoint
from workbench.providers.tdx.yuntu_sector_flow import fetch_yuntu_sector_snapshots


def change_pct(price: float, pre_close: float) -> float:
    if not pre_close:
        return 0.0
    return round((price - pre_close) / pre_close * 100, 2)


def _row_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _summary_main_net(summary: object) -> float:
    if isinstance(summary, dict):
        return float(summary.get("main_net_amount") or 0.0)
    return float(getattr(summary, "main_net_amount", 0.0) or 0.0)


def _summary_member_count(summary: object) -> int | None:
    if isinstance(summary, dict):
        raw = summary.get("member_count")
    else:
        raw = getattr(summary, "member_count", None)
    if raw is None:
        return None
    return int(raw)


def fetch_board_quote_map(
    *,
    get_board_list: Callable[..., object],
    board_page_size: int,
) -> dict[str, tuple[float, float]]:
    quote_map: dict[str, tuple[float, float]] = {}
    for board_type in (BoardType.HY, BoardType.GN, BoardType.HY2, BoardType.FG, BoardType.DQ):
        response = get_board_list(board_type=board_type, count=board_page_size)
        rows = _iter_response_rows(response)
        for row in rows:
            sector_id = str(
                _row_value(row, "code", None) or _row_value(row, "sector_id", "")
            ).strip()
            if not sector_id:
                continue
            price = float(_row_value(row, "price", 0.0) or 0.0)
            pre_close = float(_row_value(row, "pre_close", 0.0) or 0.0)
            quote_map[sector_id] = (price, pre_close)
    return quote_map


def supplement_classic_index_quotes(
    quote_map: dict[str, tuple[float, float]],
    *,
    sector_ids: Iterable[str],
    get_stock_quotes: Callable[..., object],
) -> None:
    missing = [
        sector_id
        for sector_id in sector_ids
        if sector_id.startswith("880") and sector_id not in quote_map
    ]
    if not missing:
        return
    batch_size = 80
    for offset in range(0, len(missing), batch_size):
        batch = missing[offset : offset + batch_size]
        response = get_stock_quotes([(1, sector_id) for sector_id in batch])
        for row in _iter_response_rows(response):
            sector_id = str(_row_value(row, "code", "")).strip()
            if not sector_id:
                continue
            price = float(
                _row_value(row, "close", None)
                or _row_value(row, "price", 0.0)
                or 0.0
            )
            pre_close = float(_row_value(row, "pre_close", 0.0) or 0.0)
            quote_map[sector_id] = (price, pre_close)


def fetch_sector_summaries_parallel(
    settings: WorkbenchSettings,
    sector_ids: Iterable[str],
) -> dict[str, object]:
    ids = list(sector_ids)
    if not ids:
        return {}

    port = get_port()
    hosts = tuple(MAC_HOSTS[: settings.node_pool_size])
    if not hosts:
        return {}

    def fetch_one(index: int, sector_id: str) -> tuple[str, object | None]:
        host = hosts[index % len(hosts)]
        client = MacClient(
            host=host,
            port=port,
            timeout=settings.enhanced_node_timeout_seconds,
            auto_reconnect=False,
        )
        try:
            client.connect()
            return sector_id, client.get_board_summary(sector_id)
        except Exception:
            return sector_id, None
        finally:
            try:
                client.close()
            except Exception:
                pass

    summaries: dict[str, object] = {}
    workers = min(settings.node_pool_size, len(ids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(fetch_one, index, sector_id)
            for index, sector_id in enumerate(ids)
        ]
        for future in as_completed(futures):
            sector_id, summary = future.result()
            if summary is not None:
                summaries[sector_id] = summary
    return summaries


def build_official_sector_minutes(
    *,
    trade_date: date,
    minute: str,
    sectors: Iterable[Sector],
    member_counts: dict[str, int],
    quote_map: dict[str, tuple[float, float]],
    summaries: dict[str, object],
    previous_main_cum: dict[str, float],
    observed_at: datetime,
    batch_id: str,
    yuntu_main: dict[str, float] | None = None,
    yuntu_change_pct: dict[str, float] | None = None,
) -> tuple[list[SectorMinute], list[str]]:
    records: list[SectorMinute] = []
    errors: list[str] = []
    yuntu_values = yuntu_main or {}
    yuntu_changes = yuntu_change_pct or {}
    for sector in sorted(sectors, key=lambda item: item.sector_id):
        summary = summaries.get(sector.sector_id)
        yuntu_cum = yuntu_values.get(sector.sector_id)
        if summary is None and yuntu_cum is None:
            errors.append(f"missing official summary for {sector.sector_id}")
            continue
        if yuntu_cum is not None:
            main_cum = yuntu_cum
            main_source = "tdx.yuntu.real_hq"
        else:
            main_cum = _summary_main_net(summary)
            main_source = "tdx.enhanced.board_summary"
        main_delta = main_cum - previous_main_cum.get(sector.sector_id, 0.0)
        previous_main_cum[sector.sector_id] = main_cum
        price, pre_close = quote_map.get(sector.sector_id, (0.0, 0.0))
        sector_change_pct = yuntu_changes.get(sector.sector_id)
        if sector_change_pct is None:
            sector_change_pct = change_pct(price, pre_close)
        member_count = (
            _summary_member_count(summary)
            if summary is not None
            else member_counts.get(sector.sector_id, 0)
        ) or member_counts.get(sector.sector_id, 0)
        funds = FundFlow(
            main=TierPoint(
                delta=main_delta,
                cumulative=main_cum,
                source=main_source,
                quality=DataQuality.OFFICIAL,
            ),
            super=TierPoint(
                delta=0.0,
                cumulative=0.0,
                source="tdx.unavailable",
                quality=DataQuality.GAP,
            ),
            large=TierPoint(
                delta=0.0,
                cumulative=0.0,
                source="tdx.unavailable",
                quality=DataQuality.GAP,
            ),
            medium=TierPoint(
                delta=0.0,
                cumulative=0.0,
                source="tdx.unavailable",
                quality=DataQuality.GAP,
            ),
            small=TierPoint(
                delta=0.0,
                cumulative=0.0,
                source="tdx.unavailable",
                quality=DataQuality.GAP,
            ),
        )
        records.append(
            SectorMinute(
                trade_date=trade_date,
                minute=minute,
                sector_id=sector.sector_id,
                change_pct=sector_change_pct,
                member_count=member_count,
                funds=funds,
                observed_at=observed_at,
                batch_id=batch_id,
            )
        )
    return records, errors


@dataclass(slots=True)
class OfficialSectorBatchBuilder:
    settings: WorkbenchSettings
    get_board_list: Callable[..., object]
    get_stock_quotes: Callable[..., object] | None
    board_page_size: int
    previous_main_cum: dict[str, float]

    def build(
        self,
        *,
        trade_date: date,
        minute: str,
        sectors: list[Sector],
        member_counts: dict[str, int],
        observed_at: datetime,
    ) -> tuple[list[SectorMinute], list[str]]:
        batch_id = f"{trade_date.isoformat()}T{minute}"
        sector_ids = [sector.sector_id for sector in sectors]
        yuntu_main: dict[str, float] | None = None
        yuntu_change_pct: dict[str, float] | None = None
        if self.settings.sector_yuntu_main_enabled:
            try:
                snapshots = fetch_yuntu_sector_snapshots(
                    sector_ids,
                    timeout_seconds=self.settings.enhanced_node_timeout_seconds,
                )
                if snapshots:
                    yuntu_main = {
                        sector_id: snapshot.main_yuan for sector_id, snapshot in snapshots.items()
                    }
                    yuntu_change_pct = {
                        sector_id: snapshot.change_pct for sector_id, snapshot in snapshots.items()
                    }
            except Exception:
                yuntu_main = None
                yuntu_change_pct = None

        missing_summary_ids = [
            sector_id for sector_id in sector_ids if not yuntu_main or sector_id not in yuntu_main
        ]
        summaries = (
            fetch_sector_summaries_parallel(self.settings, missing_summary_ids)
            if missing_summary_ids
            else {}
        )

        quote_map: dict[str, tuple[float, float]] = {}
        if not yuntu_change_pct or missing_summary_ids:
            quote_map = fetch_board_quote_map(
                get_board_list=self.get_board_list,
                board_page_size=self.board_page_size,
            )
            if self.get_stock_quotes is not None:
                supplement_classic_index_quotes(
                    quote_map,
                    sector_ids=sector_ids,
                    get_stock_quotes=self.get_stock_quotes,
                )
        return build_official_sector_minutes(
            trade_date=trade_date,
            minute=minute,
            sectors=sectors,
            member_counts=member_counts,
            quote_map=quote_map,
            summaries=summaries,
            previous_main_cum=self.previous_main_cum,
            observed_at=observed_at,
            batch_id=batch_id,
            yuntu_main=yuntu_main,
            yuntu_change_pct=yuntu_change_pct,
        )


def _iter_response_rows(response: object) -> list[object]:
    if response is None:
        return []
    if hasattr(response, "to_dict"):
        records = response.to_dict(orient="records")
        if isinstance(records, list):
            return records
    if isinstance(response, list):
        return response
    if hasattr(response, "__iter__") and not isinstance(response, (str, bytes, dict)):
        return list(response)
    return []
