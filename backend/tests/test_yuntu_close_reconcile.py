from __future__ import annotations

from datetime import date, datetime

from workbench.collector.yuntu_close_reconcile import YuntuCloseReconcileService


def test_close_reconcile_runs_twice_after_session_end() -> None:
    calls: list[tuple[date, str]] = []

    def collect(trade_date: date, minute: str) -> dict[str, object]:
        calls.append((trade_date, minute))
        return {"yuntu_stocks": 1, "yuntu_sectors": 1}

    service = YuntuCloseReconcileService(collect)
    trade_date = date(2026, 9, 22)

    assert service.reconcile_if_due(trade_date, datetime(2026, 9, 22, 15, 1)) is not None
    assert calls == [(trade_date, "15:00")]

    assert service.reconcile_if_due(trade_date, datetime(2026, 9, 22, 15, 2)) is None

    assert service.reconcile_if_due(trade_date, datetime(2026, 9, 22, 15, 3)) is not None
    assert len(calls) == 2

    assert service.reconcile_if_due(trade_date, datetime(2026, 9, 22, 15, 10)) is None


def test_close_reconcile_skips_before_afternoon_close() -> None:
    calls: list[tuple[date, str]] = []

    def collect(trade_date: date, minute: str) -> dict[str, object]:
        calls.append((trade_date, minute))
        return {"yuntu_stocks": 1}

    service = YuntuCloseReconcileService(collect)
    assert service.reconcile_if_due(date(2026, 9, 22), datetime(2026, 9, 22, 12, 0)) is None
    assert calls == []
