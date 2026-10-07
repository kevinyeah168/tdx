from __future__ import annotations

from unittest.mock import patch

from workbench.providers.tonghuashun.hot_rank import TonghuashunHotRankProvider, _rank_change_map


def test_rank_change_map_skips_missing_values() -> None:
    rows = [
        {"code": "600519", "hot_rank_chg": 3},
        {"code": "000001", "hot_rank_chg": 0},
        {"code": "", "hot_rank_chg": 5},
    ]
    assert _rank_change_map(rows) == {"600519": 3, "000001": 0}


def test_fetch_stock_rank_merges_day_rank_change() -> None:
    provider = TonghuashunHotRankProvider()
    hour_rows = [
        {
            "order": 1,
            "code": "603259",
            "name": "药明康德",
            "market": 17,
            "rate": "82693.0",
            "rise_and_fall": 4.15,
            "hot_rank_chg": 0,
        }
    ]
    day_rows = [
        {
            "order": 1,
            "code": "603259",
            "name": "药明康德",
            "market": 17,
            "rate": "82693.0",
            "rise_and_fall": 4.15,
            "hot_rank_chg": 0,
        },
        {
            "order": 2,
            "code": "000021",
            "name": "深科技",
            "market": 33,
            "rate": "40879.0",
            "rise_and_fall": -2.84,
            "hot_rank_chg": 8,
        },
    ]

    with patch.object(provider, "_fetch_stock_rows", side_effect=[hour_rows, day_rows]):
        rows = provider.fetch_stock_rank("popularity")

    assert len(rows) == 1
    assert rows[0].code == "603259"
    assert rows[0].rank_change == 0

    hour_rows.append(
        {
            "order": 2,
            "code": "000021",
            "name": "深科技",
            "market": 33,
            "rate": "40879.0",
            "rise_and_fall": -2.84,
            "hot_rank_chg": 0,
        }
    )
    with patch.object(provider, "_fetch_stock_rows", side_effect=[hour_rows, day_rows]):
        rows = provider.fetch_stock_rank("popularity")

    by_code = {row.code: row.rank_change for row in rows}
    assert by_code["000021"] == 8
