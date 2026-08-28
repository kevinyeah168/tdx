from __future__ import annotations

from pathlib import Path

from workbench.query.sector_resolve import resolve_member_sector_id
from workbench.storage.meta_store import MetaStore
from workbench.config import WorkbenchSettings


def test_resolve_member_sector_id_by_name(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    with meta.connect() as connection:
        connection.executemany(
            "INSERT INTO security_master(symbol, code, name, market, active) VALUES(?, ?, ?, ?, 1)",
            [
                ("SH600000", "600000", "浦发银行", "SH"),
                ("SZ000001", "000001", "平安银行", "SZ"),
            ],
        )
        connection.executemany(
            "INSERT INTO sector_master(sector_id, name, sector_type) VALUES(?, ?, ?)",
            [
                ("880703", "人形机器人", "concept"),
                ("888783", "人形概念", "style"),
            ],
        )
        connection.executemany(
            "INSERT INTO sector_membership(sector_id, symbol) VALUES(?, ?)",
            [
                ("880703", "SH600000"),
                ("880703", "SZ000001"),
            ],
        )
        connection.commit()
    resolved = resolve_member_sector_id(meta, "888783", sector_name="人形机器人")
    assert resolved == "880703"


def test_resolve_prefers_name_match_over_smaller_member_set(tmp_path: Path) -> None:
    meta = MetaStore(tmp_path / "meta.sqlite")
    meta.initialize()
    with meta.connect() as connection:
        connection.executemany(
            "INSERT INTO security_master(symbol, code, name, market, active) VALUES(?, ?, ?, ?, 1)",
            [
                ("SH600000", "600000", "浦发银行", "SH"),
                ("SZ000001", "000001", "平安银行", "SZ"),
                ("SZ002824", "002824", "和胜股份", "SZ"),
            ],
        )
        connection.executemany(
            "INSERT INTO sector_master(sector_id, name, sector_type) VALUES(?, ?, ?)",
            [
                ("881371", "其他板块", "style"),
                ("881071", "工业金属", "industry"),
            ],
        )
        connection.executemany(
            "INSERT INTO sector_membership(sector_id, symbol) VALUES(?, ?)",
            [
                ("881371", "SH600000"),
                ("881371", "SZ000001"),
                ("881071", "SZ002824"),
                ("881071", "SH600000"),
                ("881071", "SZ000001"),
            ],
        )
        connection.commit()
    resolved = resolve_member_sector_id(meta, "881371", sector_name="工业金属")
    assert resolved == "881071"
