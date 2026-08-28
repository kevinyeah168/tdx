from __future__ import annotations

from pathlib import Path

import pytest

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.catalog import TdxCatalogLoader
from workbench.providers.tdx.runtime import PoolBackedEnhancedClient, PoolBackedNormalClient, create_real_provider


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


class FakeNormalClient:
    def get_security_list_all(self, pages="all"):
        del pages
        import json

        return json.loads((FIXTURE_DIR / "security_list.json").read_text(encoding="utf-8"))


class FakeEnhancedClient:
    def get_board_list(self, *, board_type, count):
        del board_type, count
        import json

        return json.loads((FIXTURE_DIR / "boards.json").read_text(encoding="utf-8"))

    def get_board_members(self, board_symbol, *, count):
        del count
        import json

        rows = json.loads((FIXTURE_DIR / "board_members.json").read_text(encoding="utf-8"))
        return [row for row in rows if row["sector_id"] == board_symbol]

    def get_stock_quotes(self, stocks, fields=None):
        del fields, stocks
        import json

        return json.loads((FIXTURE_DIR / "quotes.json").read_text(encoding="utf-8"))


class FakePool:
    def __init__(self, client: object) -> None:
        self._client = client
        self.closed = False

    def execute(self, operation):
        return operation(self._client)

    def close(self) -> None:
        self.closed = True


def test_pool_backed_clients_delegate_to_node_pool() -> None:
    loader = TdxCatalogLoader(
        normal_client=FakeNormalClient(),
        enhanced_client=FakeEnhancedClient(),
        source="test.pool",
    )

    catalog = loader.load().catalog

    assert len(catalog.securities) == 3
    assert len(catalog.sectors) == 2


def test_pool_wrappers_forward_to_underlying_pool() -> None:
    normal = PoolBackedNormalClient(FakePool(FakeNormalClient()))
    rows = normal.get_security_list_all()
    assert len(rows) == 5


def test_create_real_provider_closes_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    normal_pool = FakePool(FakeNormalClient())
    enhanced_pool = FakePool(FakeEnhancedClient())
    monkeypatch.setattr(
        "workbench.providers.tdx.runtime.build_node_targets",
        lambda hosts, limit, port: (),
    )
    monkeypatch.setattr(
        "workbench.providers.tdx.runtime.TdxNodePool",
        lambda *args, **kwargs: normal_pool,
    )
    monkeypatch.setattr(
        "workbench.providers.tdx.runtime.MacNodePool",
        lambda *args, **kwargs: enhanced_pool,
    )
    provider = create_real_provider(WorkbenchSettings())
    provider.close()
    assert normal_pool.closed
    assert enhanced_pool.closed
