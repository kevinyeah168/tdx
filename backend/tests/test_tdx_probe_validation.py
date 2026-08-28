from __future__ import annotations

import math

from easy_tdx import Market
import pandas as pd
import pytest

from workbench.providers.tdx.probe_validation import (
    CapabilityUnavailable,
    ENHANCED_ORDER_BOOK_ALIASES,
    NORMAL_ORDER_BOOK_ALIASES,
    normalize_protocol_aliases,
    sample_protocol_fields,
    validate_bars,
    validate_minute_data,
    validate_official_funds,
    validate_order_book,
    validate_quotes,
    validate_security_catalog,
    validate_transactions,
)


def catalog_rows() -> list[dict[str, object]]:
    return [
        {"market": Market.SH, "code": "600000", "name": "浦发银行"},
        {"market": Market.SH, "code": "688001", "name": "科创样本"},
        {"market": Market.SZ, "code": "000001", "name": "平安银行"},
        {"market": Market.SZ, "code": "300001", "name": "创业样本"},
        {"market": Market.BJ, "code": "430047", "name": "北交样本一"},
        {"market": Market.BJ, "code": "830001", "name": "北交样本二"},
    ]


def quote_row() -> dict[str, object]:
    return {
        "market": 1,
        "code": "600000",
        "price": 12.34,
        "pre_close": 12.20,
        "open": 12.10,
        "high": 12.50,
        "low": 12.00,
        "close": 12.34,
        "vol": 1000.0,
        "amount": 12340.0,
    }


def fund_row() -> dict[str, object]:
    return {
        "market": 1,
        "code": "600000",
        "main_in": 10.0,
        "main_out": 8.0,
        "main_net": 2.0,
        "small_in": 4.0,
        "small_out": 5.0,
        "small_net": -1.0,
        "mid_in": 3.0,
        "mid_out": 2.0,
        "mid_net": 1.0,
        "large_in": 3.0,
        "large_out": 1.0,
        "large_net": 2.0,
    }


def bar_row() -> dict[str, object]:
    return {
        "market": 1,
        "code": "600000",
        "datetime": "2026-08-21T15:00:00+08:00",
        "open": 12.10,
        "high": 12.50,
        "low": 12.00,
        "close": 12.34,
        "vol": 1000.0,
        "amount": 12340.0,
    }


def canonical_order_book(levels: int = 5) -> dict[str, object]:
    row: dict[str, object] = {"market": 1, "code": "600000"}
    for level in range(1, levels + 1):
        row[f"bid{level}_price"] = 12.30 - level / 100
        row[f"bid{level}_volume"] = 1000 + level
        row[f"ask{level}_price"] = 12.34 + level / 100
        row[f"ask{level}_volume"] = 1100 + level
    return row


def test_security_catalog_requires_distinct_valid_sh_sz_bj_aggregation() -> None:
    evidence = validate_security_catalog(pd.DataFrame(catalog_rows()))

    assert {"market", "code", "name"} <= set(evidence.sample_fields)

    without_bj = [row for row in catalog_rows() if row["market"] is not Market.BJ]
    with pytest.raises(CapabilityUnavailable, match="SH/SZ/BJ"):
        validate_security_catalog(without_bj)

    duplicated = catalog_rows()[:5] + [catalog_rows()[0]]
    with pytest.raises(CapabilityUnavailable, match="unique"):
        validate_security_catalog(duplicated)


@pytest.mark.parametrize(
    "mutation",
    [
        {"code": "000001"},
        {"market": 0},
        {"price": math.nan},
        {"vol": math.inf},
        {"amount": -math.inf},
        {"pre_close": 0.0},
        {"high": 11.0},
        {"low": 13.0},
    ],
)
def test_quotes_reject_wrong_context_nonfinite_values_and_impossible_ohlc(
    mutation: dict[str, object],
) -> None:
    row = quote_row()
    row.update(mutation)

    with pytest.raises(CapabilityUnavailable):
        validate_quotes([row], expected_market=1, expected_code="600000")


def test_quotes_require_finite_price_volume_amount_and_usable_previous_close() -> None:
    evidence = validate_quotes(
        [quote_row()], expected_market=1, expected_code="600000"
    )

    assert {"price", "pre_close", "vol", "amount"} <= set(evidence.sample_fields)


def test_official_funds_accepts_missing_date_but_checks_context_and_equations() -> None:
    row = fund_row()
    assert "date" not in row

    evidence = validate_official_funds(
        [row], expected_market=1, expected_code="600000"
    )

    assert {"main_in", "main_out", "main_net", "small_net"} <= set(
        evidence.sample_fields
    )

    for mutation in (
        {"code": "000001"},
        {"main_in": math.nan},
        {"small_out": math.inf},
        {"main_net": 99.0},
        {"small_net": 99.0},
    ):
        invalid = fund_row()
        invalid.update(mutation)
        with pytest.raises(CapabilityUnavailable):
            validate_official_funds(
                [invalid], expected_market=1, expected_code="600000"
            )


@pytest.mark.parametrize(
    "mutation",
    [
        {"datetime": "not-a-date"},
        {"price": math.nan},
        {"price": 0.0},
        {"vol": -1},
        {"vol": math.inf},
    ],
)
def test_minute_data_rejects_invalid_dates_prices_and_volume(
    mutation: dict[str, object],
) -> None:
    row: dict[str, object] = {
        "datetime": "2026-08-21T14:59:00+08:00",
        "price": 12.34,
        "vol": 100,
    }
    row.update(mutation)

    with pytest.raises(CapabilityUnavailable):
        validate_minute_data([row])


def test_minute_data_accepts_parseable_datetime_positive_price_and_nonnegative_volume() -> None:
    evidence = validate_minute_data(
        [{"datetime": "2026-08-21 14:59", "price": 12.34, "vol": 0}]
    )

    assert evidence.sample_fields == ["datetime", "price", "vol"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"market": 0},
        {"code": "000001"},
        {"time": "25:01:02"},
        {"time": "not-a-time"},
        {"price": math.nan},
        {"price": 0.0},
        {"vol": -1},
        {"vol": math.inf},
    ],
)
def test_transactions_reject_invalid_context_time_price_and_volume(
    mutation: dict[str, object],
) -> None:
    row: dict[str, object] = {
        "market": 1,
        "code": "600000",
        "time": "14:59:01",
        "price": 12.34,
        "vol": 100,
    }
    row.update(mutation)

    with pytest.raises(CapabilityUnavailable):
        validate_transactions(
            [row],
            expected_market=1,
            expected_code="600000",
        )


def test_transactions_accept_parseable_time_and_requested_context() -> None:
    evidence = validate_transactions(
        [
            {
                "market": 1,
                "code": "600000",
                "time": "09:30",
                "price": 12.34,
                "vol": 0,
            }
        ],
        expected_market=1,
        expected_code="600000",
    )

    assert evidence.sample_fields == ["market", "code", "time", "price", "vol"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"code": "000001"},
        {"market": 0},
        {"datetime": "2026-02-30"},
        {"open": math.nan},
        {"amount": math.inf},
        {"vol": -1},
        {"high": 11.0},
        {"low": 13.0},
    ],
)
def test_bars_reject_wrong_context_invalid_dates_nonfinite_and_impossible_ohlc(
    mutation: dict[str, object],
) -> None:
    row = bar_row()
    row.update(mutation)

    with pytest.raises(CapabilityUnavailable):
        validate_bars([row], expected_market=1, expected_code="600000")


def test_bars_require_finite_ohlcv_amount_and_parseable_datetime() -> None:
    evidence = validate_bars(
        [bar_row()], expected_market=1, expected_code="600000"
    )

    assert {"datetime", "open", "high", "low", "close", "vol", "amount"} <= set(
        evidence.sample_fields
    )


def test_order_book_requires_finite_usable_levels_and_requested_context() -> None:
    evidence = validate_order_book(
        [canonical_order_book()],
        expected_market=1,
        expected_code="600000",
        levels=5,
    )
    assert "bid5_price" in evidence.sample_fields

    for mutation in (
        {"code": "000001"},
        {"bid1_price": math.nan},
        {"ask2_price": 0.0},
        {"bid2_volume": math.inf},
        {"ask1_volume": -1},
        {"bid5_price": None},
    ):
        invalid = canonical_order_book()
        invalid.update(mutation)
        with pytest.raises(CapabilityUnavailable):
            validate_order_book(
                [invalid],
                expected_market=1,
                expected_code="600000",
                levels=5,
            )


@pytest.mark.parametrize(
    "mutation",
    [
        {"bid2_price": 12.31},
        {"ask2_price": 12.33},
        {"bid1_price": 12.40},
    ],
)
def test_order_book_rejects_unsorted_or_crossed_prices(
    mutation: dict[str, object],
) -> None:
    row = canonical_order_book(levels=2)
    row.update(mutation)

    with pytest.raises(CapabilityUnavailable):
        validate_order_book(
            [row],
            expected_market=1,
            expected_code="600000",
            levels=2,
        )


def test_order_book_normalizes_normal_and_ambiguous_enhanced_aliases() -> None:
    normal = {
        "market": 1,
        "code": "600000",
        "bid1": 12.30,
        "bid_vol1": 100,
        "ask1": 12.31,
        "ask_vol1": 101,
        "bid2": 12.29,
        "bid_vol2": 102,
        "ask2": 12.32,
        "ask_vol2": 103,
    }
    enhanced = {
        "market": 1,
        "code": "600000",
        "bid_price": 12.30,
        "bid_volume": 100,
        "ask_price": 12.31,
        "ask_volume": 101,
        "bid2_price": 12.29,
        "limit_up_count": 102,
        "ask2_price": 12.32,
        "limit_down_count": 103,
    }

    normal_rows = normalize_protocol_aliases([normal], NORMAL_ORDER_BOOK_ALIASES)
    enhanced_rows = normalize_protocol_aliases(
        [enhanced], ENHANCED_ORDER_BOOK_ALIASES
    )

    for rows in (normal_rows, enhanced_rows):
        evidence = validate_order_book(
            rows,
            expected_market=1,
            expected_code="600000",
            levels=2,
        )
        assert {"bid2_volume", "ask2_volume"} <= set(evidence.sample_fields)
    assert enhanced_rows[0]["bid2_volume"] == 102
    assert "limit_up_count" not in enhanced_rows[0]


def test_safe_sampling_is_bounded_strict_and_never_recurses_mapping_keys() -> None:
    response = [
        {
            "market": 1,
            "code": "600000",
            "valid_field": 1,
            "nested": {"safe_but_nested": 1, "password": "secret"},
            "bad-field": 2,
            "9invalid": 3,
            "password": "secret",
            **{f"field_{index}": index for index in range(30)},
        }
    ]

    fields = sample_protocol_fields(response)

    assert len(fields) == 12
    assert fields[:4] == ["market", "code", "valid_field", "nested"]
    assert "safe_but_nested" not in fields
    assert "bad-field" not in fields
    assert "9invalid" not in fields
    assert "password" not in fields
