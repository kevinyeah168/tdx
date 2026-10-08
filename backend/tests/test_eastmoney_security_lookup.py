from __future__ import annotations

from unittest.mock import patch

from workbench.providers.eastmoney.security_lookup import (
    fetch_security_names_by_codes,
    normalize_em_symbol,
)


def test_normalize_em_symbol_fixes_bse_prefix() -> None:
    symbol, code = normalize_em_symbol("SZ920252")
    assert symbol == "BJ920252"
    assert code == "920252"


def test_normalize_em_symbol_keeps_main_board_prefix() -> None:
    symbol, code = normalize_em_symbol("SH600519")
    assert symbol == "SH600519"
    assert code == "600519"


def test_fetch_security_names_by_codes() -> None:
    with patch(
        "workbench.providers.eastmoney.security_lookup._fetch_suggest_name",
        side_effect=lambda code: {"920252": "天宏锂电", "920729": "永顺生物"}.get(code),
    ):
        names = fetch_security_names_by_codes(["920252", "920729", "000001"])
    assert names == {"920252": "天宏锂电", "920729": "永顺生物"}
