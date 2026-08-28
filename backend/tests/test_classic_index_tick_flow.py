from datetime import date, time

from workbench.providers.tdx.classic_index_tick_flow import (
    append_closing_minute,
    change_pct,
    momentum_to_main_flow,
)


class FakeTick:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        import pandas as pd

        self._df = pd.DataFrame(rows)

    def __len__(self) -> int:
        return len(self._df)

    def __getitem__(self, key: str):
        return self._df[key]

    @property
    def iloc(self):
        return self._df.iloc


def test_momentum_to_main_flow_scales_to_official_main() -> None:
    tick = FakeTick(
        [
            {"time": time(9, 30), "momentum": 1.0, "price": 100.0},
            {"time": time(9, 31), "momentum": 2.0, "price": 101.0},
        ]
    )
    flow = momentum_to_main_flow(tick, official_main_net=300.0)
    assert len(flow) == 2
    assert flow[0]["minute"] == "09:30"
    assert flow[1]["main_cum"] == 300.0


def test_append_closing_minute_adds_1500() -> None:
    flow = [
        {"minute": "14:59", "main_delta": 10.0, "main_cum": 90.0, "price": 50.0},
    ]
    closed = append_closing_minute(flow, official_main_net=100.0, closing_price=51.0)
    assert closed[-1]["minute"] == "15:00"
    assert closed[-1]["main_cum"] == 100.0
    assert closed[-1]["main_delta"] == 10.0


def test_change_pct() -> None:
    assert change_pct(95.0, 100.0) == -5.0
