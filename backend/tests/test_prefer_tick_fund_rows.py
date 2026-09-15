from workbench.storage.hot_store import HotStore


def test_snapshot_fund_rows_drops_legacy_tick_rows() -> None:
    rows = [
        {"minute": "09:30", "main_cum": 1e8, "batch_id": "2026-09-03Tbackfill-tick"},
        {"minute": "10:01", "main_cum": 9e9, "batch_id": "2026-09-03T10:01-yuntu"},
    ]
    merged = HotStore._prefer_tick_fund_rows(rows)
    assert [row["minute"] for row in merged] == ["10:01"]
    assert merged[0]["main_cum"] == 9e9


def test_snapshot_fund_rows_keeps_yuntu_minutes_in_order() -> None:
    rows = [
        {"minute": "14:58", "main_cum": 1.0e9, "batch_id": "2026-09-03T14:58-yuntu"},
        {"minute": "14:59", "main_cum": 1.05e9, "batch_id": "2026-09-03T14:59-yuntu"},
    ]
    merged = HotStore._prefer_tick_fund_rows(rows)
    assert len(merged) == 2
    assert merged[-1]["minute"] == "14:59"
    assert merged[-1]["main_cum"] == 1.05e9


def test_snapshot_fund_rows_ignores_flat_zero_tick_when_yuntu_exists() -> None:
    rows = [
        {"minute": "09:30", "main_cum": 0.0, "batch_id": "2026-09-04Tbackfill-tick"},
        {"minute": "15:00", "main_cum": 2.3e8, "batch_id": "2026-09-04T15:00-yuntu"},
    ]
    merged = HotStore._prefer_tick_fund_rows(rows)
    assert len(merged) == 1
    assert merged[0]["minute"] == "15:00"
    assert merged[0]["main_cum"] == 2.3e8
