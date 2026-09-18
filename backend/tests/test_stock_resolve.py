from __future__ import annotations

from pathlib import Path

from workbench.domain import Security
from workbench.query.stocks import StockQueryService
from workbench.storage.meta_store import MetaStore


def test_resolve_symbols(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    meta.replace_catalog(
        securities=[
            Security(symbol="SH600000", code="600000", name="浦发银行", market="SH", active=True),
            Security(symbol="SZ000001", code="000001", name="平安银行", market="SZ", active=True),
        ],
        sectors=[],
        memberships=[],
        version="test",
    )
    service = StockQueryService(meta)
    payload = service.resolve_symbols(["600000", "SH600000", "平安银行", "missing"])
    assert [item["symbol"] for item in payload["resolved"]] == ["SH600000", "SZ000001"]
    assert payload["unresolved"] == ["missing"]
