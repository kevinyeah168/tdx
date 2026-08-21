from __future__ import annotations

from datetime import datetime
import inspect
from typing import Any

from easy_tdx import MacClient, Market, Period, TdxClient
import easy_tdx.client as easy_client_module
from easy_tdx.codec.bitmap import FieldBit
from easy_tdx.commands.security_list import GetSecurityListCmd
from easy_tdx.mac.commands.symbol_bar import SymbolBarCmd
from easy_tdx.mac.commands.symbol_capital_flow import SymbolCapitalFlowCmd
from easy_tdx.mac.commands.symbol_quotes import SymbolQuotesCmd
from easy_tdx.mac.models import CapitalFlowData, MacBar, MacQuoteField
from easy_tdx.models.security import SecurityInfo
import pytest

from workbench.providers.tdx import probe as tdx_probe
from workbench.providers.tdx.clients import NormalProbeClient
from workbench.providers.tdx.probe_validation import (
    ENHANCED_ORDER_BOOK_ALIASES,
    normalize_protocol_aliases,
    validate_order_book,
)


def test_installed_full_list_signature_and_real_page_mechanism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed_signature = inspect.signature(TdxClient.get_security_list_all)
    protocol_signature = inspect.signature(NormalProbeClient.get_security_list_all)
    assert list(installed_signature.parameters) == ["self", "pages"]
    assert installed_signature.parameters["pages"].default == "all"
    assert protocol_signature.parameters["pages"].default == "all"

    client = TdxClient(
        host="contract.invalid",
        port=7709,
        timeout=0.1,
        auto_reconnect=False,
    )
    command_pages: list[tuple[Market, int, bytes]] = []
    monkeypatch.setattr(easy_client_module, "_load_cache", lambda: None)
    monkeypatch.setattr(easy_client_module, "_save_cache", lambda _rows: None)
    monkeypatch.setattr(client, "get_report_file", lambda _name: b"")
    monkeypatch.setattr(client, "get_security_count", lambda _market: 1001)

    def execute(command: Any) -> list[SecurityInfo]:
        assert isinstance(command, GetSecurityListCmd)
        request = command.build_request()
        command_pages.append((command.market, command.start, request))
        code = "600000" if command.market is Market.SH else "000001"
        return [
            SecurityInfo(
                market=command.market,
                code=code,
                name="契约样本",
                volunit=100,
                decimal_point=2,
                pre_close=12.0,
            )
        ]

    monkeypatch.setattr(client, "_execute", execute)

    result = client.get_security_list_all()

    assert [(market, start) for market, start, _ in command_pages] == [
        (Market.SH, 0),
        (Market.SH, 1000),
        (Market.SZ, 0),
        (Market.SZ, 1000),
    ]
    assert all(request for _, _, request in command_pages)
    assert set(result["market"]) == {Market.SH, Market.SZ}


def test_real_mac_quote_and_order_book_command_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MacClient(
        host="contract.invalid",
        port=7709,
        timeout=0.1,
        auto_reconnect=False,
    )
    commands: list[SymbolQuotesCmd] = []

    def execute(command: Any) -> list[MacQuoteField]:
        assert isinstance(command, SymbolQuotesCmd)
        assert command.build_request()
        commands.append(command)
        fields = {
            "bid_price": 12.30,
            "bid_volume": 100,
            "ask_price": 12.31,
            "ask_volume": 101,
            "bid2_price": 12.29,
            "limit_up_count": 102,
            "ask2_price": 12.32,
            "limit_down_count": 103,
            "pre_close": 12.20,
            "open": 12.10,
            "high": 12.50,
            "low": 12.00,
            "close": 12.34,
            "vol": 1000,
            "amount": 12340.0,
        }
        return [MacQuoteField(market=1, code="600000", name="浦发银行", fields=fields)]

    monkeypatch.setattr(client, "_execute", execute)

    quote = client.get_stock_quotes(
        [(1, "600000")], fields=tdx_probe.ENHANCED_QUOTE_FIELDS
    )
    plan = tdx_probe.enhanced_handicap_plan()
    order_book = client.get_stock_quotes([(1, "600000")], fields=plan.fields)

    assert len(commands) == 2
    assert quote.loc[0, "code"] == "600000"
    normalized = normalize_protocol_aliases(
        order_book,
        ENHANCED_ORDER_BOOK_ALIASES,
    )
    evidence = validate_order_book(
        normalized,
        expected_market=1,
        expected_code="600000",
        levels=2,
    )
    assert {"bid2_volume", "ask2_volume"} <= set(evidence.sample_fields)


def test_real_capital_flow_and_kline_client_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MacClient(
        host="contract.invalid",
        port=7709,
        timeout=0.1,
        auto_reconnect=False,
    )
    command_types: list[type[object]] = []

    def execute(command: Any) -> object:
        assert command.build_request()
        command_types.append(type(command))
        if isinstance(command, SymbolCapitalFlowCmd):
            return CapitalFlowData(
                date="",
                main_in=10.0,
                main_out=8.0,
                main_net=2.0,
                small_in=4.0,
                small_out=5.0,
                small_net=-1.0,
            )
        if isinstance(command, SymbolBarCmd):
            return [
                MacBar(
                    datetime=datetime(2026, 8, 21),
                    open=12.10,
                    high=12.50,
                    low=12.00,
                    close=12.34,
                    vol=1000.0,
                    amount=12340.0,
                )
            ]
        raise AssertionError(type(command))

    monkeypatch.setattr(client, "_execute", execute)

    funds = client.get_capital_flow(1, "600000")
    bars = client.get_stock_kline(1, "600000", Period.DAILY, 0, 3)

    assert command_types == [SymbolCapitalFlowCmd, SymbolBarCmd]
    assert funds.loc[0, "main_net"] == 2.0
    assert bars.loc[0, "close"] == 12.34


def test_ambiguous_field_alias_is_normalized_by_requested_semantics() -> None:
    assert FieldBit.BID2_VOLUME.value == FieldBit.LIMIT_UP_COUNT.value
    assert FieldBit.BID2_VOLUME.field_name == "limit_up_count"

    rows = normalize_protocol_aliases(
        [{"limit_up_count": 321}],
        ENHANCED_ORDER_BOOK_ALIASES,
    )

    assert rows == [{"bid2_volume": 321}]


def test_full_handicap_support_is_dynamic_not_version_hardcoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FutureSymbolQuotesCmd:
        def __init__(self, _stocks: object, _fields: object) -> None:
            pass

        def build_request(self) -> bytes:
            return b"future-full-handicap"

    monkeypatch.setattr(
        tdx_probe,
        "build_bitmap",
        lambda _fields: bytearray(b"\x00" * 24),
    )
    monkeypatch.setattr(tdx_probe, "SymbolQuotesCmd", FutureSymbolQuotesCmd)

    plan = tdx_probe.enhanced_handicap_plan()

    assert plan.levels == 5
    assert plan.limitation is None
    assert {bit.value for bit in plan.fields} >= {128, 130, 133, 139}
