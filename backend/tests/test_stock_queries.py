from __future__ import annotations

from pathlib import Path

from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.query.stocks import ReplayQueryService, StockQueryService
from workbench.storage.history_store import HistoryStore
from workbench.storage.meta_store import MetaStore
from workbench.providers.tdx.bars import normalize_bar_row
import json


def seed_meta(path: Path) -> MetaStore:
    meta = MetaStore(path)
    meta.initialize()
    meta.replace_catalog(
        securities=[Security(symbol="SH600000", code="600000", name="浦发银行", market="SH")],
        sectors=[Sector(sector_id="881001", name="银行", sector_type="industry")],
        memberships=[Membership(sector_id="881001", symbol="SH600000")],
        version="catalog-test",
        source="test",
    )
    return meta


def test_stock_security_lookup(tmp_path: Path) -> None:
    meta = seed_meta(tmp_path / "meta.sqlite")
    payload = StockQueryService(meta).security("sh600000")
    assert payload is not None
    assert payload["name"] == "浦发银行"


def test_stock_sectors_lookup(tmp_path: Path) -> None:
    meta = seed_meta(tmp_path / "meta.sqlite")
    items = StockQueryService(meta).sectors_for("SH600000")
    assert items[0]["sector_id"] == "881001"


def test_history_bars_lookup(tmp_path: Path) -> None:
    meta = seed_meta(tmp_path / "meta.sqlite")
    history = HistoryStore(tmp_path / "history.sqlite")
    history.initialize()
    rows = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "tdx" / "bars.json").read_text(encoding="utf-8")
    )
    bars = [normalize_bar_row(row, symbol="SH600000", period="day") for row in rows]
    history.replace_bars(symbol="SH600000", period="day", bars=bars, source="test")
    payload, gap = StockQueryService(meta, history=history).bars("SH600000", "day", 2)
    assert gap is None
    assert len(payload) == 2


def test_replay_available_dates(tmp_path: Path) -> None:
    meta = seed_meta(tmp_path / "meta.sqlite")
    hot_dir = tmp_path / "hot"
    hot_dir.mkdir()
    (hot_dir / "2026-08-20.sqlite").write_text("", encoding="utf-8")
    settings = WorkbenchSettings(data_dir=tmp_path)
    dates = ReplayQueryService(settings.data_dir, meta).available_dates()
    assert dates == ["2026-08-20"]
