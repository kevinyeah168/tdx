from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import date, datetime

from workbench.collector.trading_clock import is_trading_day, is_trading_minute


CollectFn = Callable[[date, str], dict[str, object]]
SleepFn = Callable[[float], None]
TickFn = Callable[[], None]
BackfillFn = Callable[[date, datetime], dict[str, object] | None]


CollectorMode = str  # "hot" | "archive" | "combined" | "gray"


class MinuteScheduler:
    def __init__(
        self,
        *,
        collect: CollectFn,
        sleep: SleepFn = time.sleep,
        quote_interval_seconds: float = 5.0,
        priority_collect: CollectFn | None = None,
        priority_interval_seconds: float = 5.0,
        full_collect_interval_seconds: float = 45.0,
        session_backfill: BackfillFn | None = None,
        gray_collect: CollectFn | None = None,
        gray_interval_seconds: float = 15.0,
        yuntu_finalize: Callable[[date], dict[str, object] | None] | None = None,
        yuntu_close_reconcile: Callable[[date, datetime], dict[str, object] | None] | None = None,
        on_tick: TickFn | None = None,
        mode: CollectorMode = "combined",
    ) -> None:
        if quote_interval_seconds <= 0:
            raise ValueError("quote_interval_seconds must be positive")
        if priority_interval_seconds <= 0:
            raise ValueError("priority_interval_seconds must be positive")
        if full_collect_interval_seconds <= 0:
            raise ValueError("full_collect_interval_seconds must be positive")
        if gray_interval_seconds <= 0:
            raise ValueError("gray_interval_seconds must be positive")
        self._collect = collect
        self._priority_collect = priority_collect
        self._session_backfill = session_backfill
        self._gray_collect = gray_collect
        self._yuntu_finalize = yuntu_finalize
        self._yuntu_close_reconcile = yuntu_close_reconcile
        self._sleep = sleep
        self._quote_interval_seconds = quote_interval_seconds
        self._priority_interval_seconds = priority_interval_seconds
        self._full_collect_interval_seconds = full_collect_interval_seconds
        self._gray_interval_seconds = gray_interval_seconds
        self._on_tick = on_tick
        self._last_full_collect_at = 0.0
        self._last_gray_collect_at = 0.0
        if mode not in {"hot", "archive", "combined", "gray"}:
            raise ValueError("mode must be hot, archive, combined, or gray")
        self._mode = mode

    def serve(self) -> None:
        while True:
            if self._on_tick is not None:
                self._on_tick()
            now = datetime.now()
            if not is_trading_day(now.date()):
                self._sleep(60.0)
                continue

            clock = now.time().replace(second=0, microsecond=0)
            if not is_trading_minute(clock):
                if self._mode == "gray":
                    self._sleep(1.0)
                    continue
                if self._yuntu_finalize is not None:
                    try:
                        finalized = self._yuntu_finalize(now.date())
                        if finalized is not None:
                            print(
                                json.dumps(
                                    {"mode": "yuntu-finalize", **finalized},
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            )
                    except Exception as error:
                        print(f"yuntu finalize failed: {error}", file=sys.stderr)
                if self._yuntu_close_reconcile is not None:
                    try:
                        reconciled = self._yuntu_close_reconcile(now.date(), now)
                        if reconciled is not None:
                            print(
                                json.dumps(reconciled, ensure_ascii=False, separators=(",", ":"))
                            )
                    except Exception as error:
                        print(f"yuntu close reconcile failed: {error}", file=sys.stderr)
                if self._mode != "hot" and self._session_backfill is not None:
                    try:
                        self._session_backfill(now.date(), now)
                    except Exception as error:
                        print(f"session backfill failed: {error}", file=sys.stderr)
                self._sleep(1.0)
                continue

            if self._mode == "archive":
                self._sleep(max(self._priority_interval_seconds, 1.0))
                continue

            minute = now.strftime("%H:%M")
            now_ts = now.timestamp()
            cycle_started = time.perf_counter()

            if self._mode == "gray":
                try:
                    due_gray = (now_ts - self._last_gray_collect_at) >= self._gray_interval_seconds
                    if self._gray_collect is not None and due_gray:
                        self._last_gray_collect_at = now_ts
                        gray_result = self._gray_collect(now.date(), minute)
                        print(
                            json.dumps(
                                {"mode": "gray", **gray_result},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        )
                except Exception as error:
                    print(f"gray collect failed: {error}", file=sys.stderr)
                    self._sleep(5.0)
                    continue
                elapsed = time.perf_counter() - cycle_started
                self._sleep(max(1.0, self._gray_interval_seconds - elapsed))
                continue

            due_full = (now_ts - self._last_full_collect_at) >= self._full_collect_interval_seconds
            try:
                # 盘中不做阻塞式全量（5216 股一次可达数分钟，会漏分钟）；仅走优先快路径
                if due_full and self._priority_collect is None:
                    result = self._collect(now.date(), minute)
                    self._last_full_collect_at = now_ts
                    print(json.dumps({"mode": "full", **result}, ensure_ascii=False, separators=(",", ":")))
                elif self._priority_collect is not None:
                    result = self._priority_collect(now.date(), minute)
                    print(
                        json.dumps(
                            {"mode": "yuntu", **result},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
            except Exception as error:
                print(f"collector minute failed: {error}", file=sys.stderr)
                self._sleep(5.0)
                continue

            interval = (
                self._quote_interval_seconds
                if due_full and self._priority_collect is None
                else self._priority_interval_seconds
            )
            elapsed = time.perf_counter() - cycle_started
            self._sleep(max(1.0, interval - elapsed))
