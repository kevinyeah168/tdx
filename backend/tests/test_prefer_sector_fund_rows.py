from workbench.storage.hot_store import HotStore


def test_snapshot_fund_rows_drops_tick_backfill() -> None:
    rows = [
        {"minute": "11:00", "main_cum": -2.67e9, "batch_id": "2026-09-14Tbackfill-tick"},
        {"minute": "11:01", "main_cum": -1.17e9, "batch_id": "2026-09-14T11:01-yuntu"},
    ]
    merged = HotStore._snapshot_fund_rows(rows)
    assert [row["minute"] for row in merged] == ["11:01"]
    assert merged[0]["main_cum"] == -1.17e9


def test_snapshot_fund_rows_prefers_yuntu_over_legacy_for_same_minute() -> None:
    rows = [
        {"minute": "11:12", "main_cum": -4.0e9, "batch_id": "2026-09-14T11:12"},
        {"minute": "11:12", "main_cum": -4.62e9, "batch_id": "2026-09-14T11:12-yuntu"},
    ]
    merged = HotStore._snapshot_fund_rows(rows)
    assert len(merged) == 1
    assert merged[0]["main_cum"] == -4.62e9


def test_snapshot_fund_rows_keeps_official_rows_without_tick() -> None:
    rows = [
        {"minute": "10:00", "main_cum": -2.0e9, "batch_id": "2026-09-14T10:00-yuntu"},
        {"minute": "10:01", "main_cum": -2.05e9, "batch_id": "2026-09-14T10:01-yuntu"},
    ]
    merged = HotStore._prefer_sector_fund_rows(rows)
    assert merged[-1]["minute"] == "10:01"
    assert merged[-1]["main_cum"] == -2.05e9
