from datetime import date, datetime, timezone

from workbench.domain import DataQuality, Sector
from workbench.providers.tdx.board_sectors import (
    build_official_sector_minutes,
    change_pct,
    fetch_board_quote_map,
)


def test_change_pct_matches_board_list_formula() -> None:
    assert change_pct(103.0, 100.0) == 3.0
    assert change_pct(0.0, 0.0) == 0.0


def test_fetch_board_quote_map_reads_price_and_pre_close() -> None:
    def fake_board_list(*, board_type: object, count: int) -> list[dict[str, object]]:
        _ = board_type, count
        return [{"code": "881319", "price": 100.0, "pre_close": 103.13}]

    quote_map = fetch_board_quote_map(get_board_list=fake_board_list, board_page_size=10)

    assert quote_map["881319"] == (100.0, 103.13)


def test_build_official_sector_minutes_prefers_yuntu_main_when_available() -> None:
    previous: dict[str, float] = {"880656": 0.0}
    observed_at = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    yuntu_main = {"880656": -47_000_000_000.0}

    sectors, errors = build_official_sector_minutes(
        trade_date=date(2026, 8, 24),
        minute="15:00",
        sectors=[Sector(sector_id="880656", name="CPO", sector_type="concept")],
        member_counts={"880656": 42},
        quote_map={"880656": (100.0, 98.0)},
        summaries={"880656": {"main_net_amount": -21_000_000_000.0, "member_count": 42}},
        previous_main_cum=previous,
        observed_at=observed_at,
        batch_id="2026-08-24T15:00",
        yuntu_main=yuntu_main,
    )

    assert errors == []
    assert sectors[0].funds.main.cumulative == -47_000_000_000.0
    assert sectors[0].funds.main.source == "tdx.yuntu.real_hq"


def test_build_official_sector_minutes_uses_mac_main_and_board_change_pct() -> None:
    previous: dict[str, float] = {"881319": -100.0}
    observed_at = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)

    sectors, errors = build_official_sector_minutes(
        trade_date=date(2026, 8, 24),
        minute="15:00",
        sectors=[Sector(sector_id="881319", name="半导体", sector_type="industry")],
        member_counts={"881319": 180},
        quote_map={"881319": (100.0, 103.13)},
        summaries={"881319": {"main_net_amount": -16312395711.375, "member_count": 184}},
        previous_main_cum=previous,
        observed_at=observed_at,
        batch_id="2026-08-24T15:00",
    )

    assert errors == []
    assert len(sectors) == 1
    sector = sectors[0]
    assert sector.sector_id == "881319"
    assert sector.member_count == 184
    assert sector.change_pct == -3.04
    assert sector.funds.main.cumulative == -16312395711.375
    assert sector.funds.main.delta == -16312395711.375 + 100.0
    assert sector.funds.main.source == "tdx.enhanced.board_summary"
    assert sector.funds.main.quality is DataQuality.OFFICIAL
    assert previous["881319"] == -16312395711.375
