from workbench.providers.tdx.sector_float_cap import (
    avg_price_from_quote_row,
    build_symbol_free_float_cap_details,
    build_symbol_free_float_caps,
    build_symbol_live_main_cum,
    daily_amount_from_quote_row,
    free_float_cap_from_quote_row,
    live_price_from_quote_row,
)


def test_live_price_prefers_price_over_close() -> None:
    row = {"price": 100.0, "close": 90.0, "circulating_capital_z": 1.0}
    assert live_price_from_quote_row(row) == 100.0
    # 1 万股 * 10000 * 100 = 1_000_000
    assert free_float_cap_from_quote_row(row) == 1_000_000.0


def test_live_price_falls_back_to_close() -> None:
    row = {"close": 88.5, "circulating_capital_z": 2.0}
    assert live_price_from_quote_row(row) == 88.5
    assert free_float_cap_from_quote_row(row) == 2.0 * 10_000.0 * 88.5


def test_avg_price_from_amount_vol() -> None:
    # amount / (vol手 * 100) = 1_050_000 / 100_000 = 10.5
    row = {"amount": 1_050_000.0, "vol": 1000.0, "price": 11.0, "circulating_capital_z": 1.0}
    assert avg_price_from_quote_row(row) == 10.5


def test_avg_price_prefers_explicit_field() -> None:
    row = {"avg_price": 10.2, "amount": 1_050_000.0, "vol": 1000.0, "price": 11.0}
    assert avg_price_from_quote_row(row) == 10.2


def test_daily_amount_from_quote_row() -> None:
    assert daily_amount_from_quote_row({"amount": 1_050_000.0}) == 1_050_000.0
    assert daily_amount_from_quote_row({"turnover": 2_000_000.0}) == 2_000_000.0


def test_build_live_main_cum_from_quote_client() -> None:
    class Client:
        def get_stock_quotes(self, stocks):  # noqa: ANN001
            return [
                {
                    "market": 0,
                    "code": "301396",
                    "main_net_amount": 761_428_992.0,
                }
            ]

    caps = build_symbol_live_main_cum(Client(), ["SZ301396"])
    assert caps["SZ301396"] == 761_428_992.0


def test_build_caps_uses_live_price_each_call() -> None:
    class Client:
        def __init__(self) -> None:
            self.price = 10.0

        def get_stock_quotes(self, stocks):  # noqa: ANN001
            return [
                {
                    "market": 0,
                    "code": "300308",
                    "price": self.price,
                    "close": 9.0,
                    "avg_price": self.price - 0.5,
                    "circulating_capital_z": 100.0,
                }
            ]

    client = Client()
    first = build_symbol_free_float_caps(client, ["SZ300308"])
    assert first["SZ300308"] == 100.0 * 10_000.0 * 10.0
    details = build_symbol_free_float_cap_details(client, ["SZ300308"])
    assert details["SZ300308"].live == 100.0 * 10_000.0 * 10.0
    assert details["SZ300308"].avg == 100.0 * 10_000.0 * 9.5
    client.price = 11.0
    second = build_symbol_free_float_caps(client, ["SZ300308"])
    assert second["SZ300308"] == 100.0 * 10_000.0 * 11.0
