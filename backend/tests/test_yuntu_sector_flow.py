from __future__ import annotations

import base64

from workbench.providers.tdx.yuntu_sector_flow import (
    build_sector_main_map,
    build_sector_snapshot_map,
    decode_gg_list,
    decode_real_hq_script,
    encode_gg_list_from_items,
    main_yuan_from_wan,
)


def _script_from_items(items: list[dict[str, object]]) -> str:
    payload = base64.b64encode(encode_gg_list_from_items(items)).decode("ascii")
    return f"/*fixture*/\nvar G_REAL_HQ = [\"{payload}\"];"


def test_decode_gg_list_roundtrip() -> None:
    items = [
        {
            "stockcode": "880656",
            "setcode": 1,
            "dqzf": 1.23,
            "f_amo_sum_wan": -4700.5,
            "now": 6191.64,
            "z_close": 6129.71,
        }
    ]
    rows = decode_gg_list(encode_gg_list_from_items(items))
    assert len(rows) == 1
    row = rows[0]
    assert row.stockcode == "880656"
    assert abs(row.f_amo_sum_wan + 4700.5) < 0.01
    assert abs(row.dqzf - 1.23) < 0.01


def test_decode_real_hq_script_builds_sector_main_map() -> None:
    script = _script_from_items(
        [
            {"stockcode": "880656", "f_amo_sum_wan": -4700.0, "dqzf": 0.0098},
            {"stockcode": "881319", "f_amo_sum_wan": -3500.0, "dqzf": -0.0108},
            {"stockcode": "000001", "f_amo_sum_wan": 12.5, "dqzf": 0.2},
        ]
    )
    rows = decode_real_hq_script(script)
    main_map = build_sector_main_map(rows, ["880656", "881319"])
    snapshots = build_sector_snapshot_map(rows, ["880656", "881319"])
    assert main_map == {
        "880656": main_yuan_from_wan(-4700.0),
        "881319": main_yuan_from_wan(-3500.0),
    }
    assert snapshots["880656"].change_pct == 0.98
    assert snapshots["881319"].change_pct == -1.08
