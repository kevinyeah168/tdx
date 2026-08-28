from __future__ import annotations

from pathlib import Path

from workbench.providers.tdx.local_catalog import load_local_security_rows
from workbench.providers.tdx.symbols import is_a_share


def test_load_local_security_rows_reads_tnf_when_present() -> None:
    tdx_home = Path("C:/new_tdx64")
    if not (tdx_home / "T0002" / "hq_cache" / "shs.tnf").is_file():
        return

    rows = load_local_security_rows(tdx_home)
    a_shares = [row for row in rows if is_a_share(row["market"], row["code"])]

    assert len(rows) > 0
    assert len(a_shares) > 0
    assert any(row["market"] == "SH" for row in a_shares)
    assert any(row["market"] == "SZ" for row in a_shares)
