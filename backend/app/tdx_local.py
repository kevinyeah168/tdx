from __future__ import annotations

from pathlib import Path
from typing import Iterable

MARKET_PREFIX = {
    "0": "SZ",
    "1": "SH",
    "2": "BJ",
}

PREFIX_MARKET = {
    "SZ": 0,
    "SH": 1,
    "BJ": 2,
}


def parse_blk_code(raw: str) -> str | None:
    """Parse TDX blk line like '1999999' / '0920083' into 'SH999999'."""
    s = raw.strip()
    if not s:
        return None
    if s[0].isdigit() and len(s) >= 7:
        market = MARKET_PREFIX.get(s[0])
        code = s[1:7]
        if market and code.isdigit():
            return f"{market}{code}"
    up = s.upper().replace(".", "")
    for p in ("SH", "SZ", "BJ"):
        if up.startswith(p) and len(up) >= len(p) + 6:
            return f"{p}{up[len(p):len(p)+6]}"
    if len(s) == 6 and s.isdigit():
        if s.startswith(("5", "6", "9")):
            return f"SH{s}"
        if s.startswith(("4", "8")):
            return f"BJ{s}"
        return f"SZ{s}"
    return None


def split_symbol(symbol: str) -> tuple[int, str]:
    sym = symbol.upper().replace(".", "")
    for p, m in PREFIX_MARKET.items():
        if sym.startswith(p):
            return m, sym[len(p) :]
    raise ValueError(f"bad symbol: {symbol}")


def read_blk_file(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    text = path.read_text(encoding="gbk", errors="ignore")
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        sym = parse_blk_code(line)
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def list_custom_blocks(tdx_root: Path) -> list[dict]:
    """Return custom blocks from T0002/blocknew (excluding zxg)."""
    root = tdx_root / "T0002" / "blocknew"
    if not root.exists():
        return []
    blocks: list[dict] = []
    for blk in sorted(root.glob("*.blk")):
        name = blk.stem
        if name.lower() == "zxg":
            continue
        codes = read_blk_file(blk)
        # companion name file: xxx.blk.nam or name in same stem .nam
        title = name
        nam = root / f"{name}.blk.nam"
        if not nam.exists():
            nam = root / f"{name}.nam"
        if nam.exists():
            title = nam.read_text(encoding="gbk", errors="ignore").strip() or name
        if codes:
            blocks.append({"id": name, "name": title, "codes": codes, "source": "tdx_blocknew"})
    return blocks


def read_watchlist(tdx_root: Path) -> list[str]:
    path = tdx_root / "T0002" / "blocknew" / "zxg.blk"
    return read_blk_file(path)


def normalize_codes(codes: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in codes:
        sym = parse_blk_code(str(c))
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out
