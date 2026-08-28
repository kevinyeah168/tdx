from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from workbench.collector.main import collect_once
from workbench.providers.tdx.provider import TdxMarketProvider
from workbench.config import WorkbenchSettings
from tools.verify_real_batch import verify


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "tdx"


def test_verify_real_batch_accepts_fixture_collection(tmp_path: Path) -> None:
    provider = TdxMarketProvider(WorkbenchSettings(data_dir=tmp_path / "data"), fixture_dir=FIXTURE_DIR)
    result = collect_once(
        trade_date=date(2026, 8, 20),
        minute="09:31",
        data_dir=tmp_path / "data",
        provider=provider,
    )

    payload = verify(tmp_path / "data", "2026-08-20", "09:31")

    assert payload["ok"] is True
    assert result["status"] == "complete"
