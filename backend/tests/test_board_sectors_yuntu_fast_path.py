from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

from workbench.config import WorkbenchSettings
from workbench.domain import Sector
from workbench.providers.tdx.board_sectors import OfficialSectorBatchBuilder
from workbench.providers.tdx.yuntu_sector_flow import YuntuSectorSnapshot


def test_builder_skips_mac_summaries_when_yuntu_covers_targets() -> None:
    settings = WorkbenchSettings(sector_yuntu_main_enabled=True)
    builder = OfficialSectorBatchBuilder(
        settings=settings,
        get_board_list=lambda **kwargs: [],
        get_stock_quotes=None,
        board_page_size=100,
        previous_main_cum={},
    )
    snapshots = {
        "880656": YuntuSectorSnapshot(main_yuan=-93_000_000_000.0, change_pct=0.98),
        "880550": YuntuSectorSnapshot(main_yuan=50_000_000_000.0, change_pct=1.99),
    }
    with patch(
        "workbench.providers.tdx.board_sectors.fetch_yuntu_sector_snapshots",
        return_value=snapshots,
    ) as fetch_yuntu, patch(
        "workbench.providers.tdx.board_sectors.fetch_sector_summaries_parallel",
    ) as fetch_mac, patch(
        "workbench.providers.tdx.board_sectors.fetch_board_quote_map",
    ) as fetch_quotes:
        sectors, errors = builder.build(
            trade_date=date(2026, 9, 14),
            minute="15:00",
            sectors=[
                Sector(sector_id="880656", name="CPO", sector_type="concept"),
                Sector(sector_id="880550", name="PCB", sector_type="concept"),
            ],
            member_counts={"880656": 10, "880550": 12},
            observed_at=datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc),
        )

    fetch_yuntu.assert_called_once()
    fetch_mac.assert_not_called()
    fetch_quotes.assert_not_called()
    assert errors == []
    assert len(sectors) == 2
    by_id = {sector.sector_id: sector for sector in sectors}
    assert by_id["880656"].funds.main.source == "tdx.yuntu.real_hq"
    assert by_id["880550"].change_pct == 1.99
