from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_COLORS = [
    "#5470c6",
    "#91cc75",
    "#fac858",
    "#ee6666",
    "#73c0de",
    "#3ba272",
    "#fc8452",
    "#9a60b4",
    "#ea7ccc",
    "#2f4554",
    "#61a0a8",
    "#d48265",
    "#749f83",
    "#ca8622",
    "#bda29a",
]


def sector_id_from_code(code: str) -> int:
    return int(code)


def stock_id_from_symbol(symbol: str) -> int:
    sym = symbol.upper().replace(".", "")
    market_digit = 1
    code = sym
    if sym.startswith("SH"):
        market_digit = 1
        code = sym[2:]
    elif sym.startswith("SZ"):
        market_digit = 2
        code = sym[2:]
    elif sym.startswith("BJ"):
        market_digit = 3
        code = sym[2:]
    return market_digit * 1_000_000 + int(code)


def symbol_from_stock_id(stock_id: int) -> str:
    market_digit = stock_id // 1_000_000
    code = str(stock_id % 1_000_000).zfill(6)
    prefix = {1: "SH", 2: "SZ", 3: "BJ"}.get(market_digit, "SH")
    return f"{prefix}{code}"


class LocalMemberStore:
    """Local persistence for sector/stock selections (no login)."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.sectors_path = project_root / "member_sectors.yaml"
        self.stocks_path = project_root / "member_stocks.yaml"
        self.sector_limit = 15
        self.stock_limit = 15

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def _sector_code(self, item: dict[str, Any]) -> str:
        return str(item.get("sourceCode") or item.get("code") or item.get("id") or "").strip()

    def get_sector_configs(self) -> list[dict[str, Any]]:
        data = self._read_yaml(self.sectors_path)
        rows = data.get("sectors") or []
        out: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            code = self._sector_code(row)
            if not code.isdigit():
                continue
            sid = int(row.get("id") or sector_id_from_code(code))
            out.append(
                {
                    "id": sid,
                    "displayName": str(row.get("displayName") or row.get("name") or code),
                    "sectorType": str(row.get("sectorType") or "HY"),
                    "sourceName": str(row.get("sourceName") or row.get("displayName") or row.get("name") or code),
                    "sourceCode": code,
                    "sortOrder": int(row.get("sortOrder") if row.get("sortOrder") is not None else idx),
                    "color": str(row.get("color") or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]),
                    "displayEnabled": True,
                    "realtimeFetchEnabled": True,
                    "customColor": row.get("customColor"),
                }
            )
        out.sort(key=lambda x: x["sortOrder"])
        return out

    def set_sector_configs(
        self,
        sector_ids: list[int],
        *,
        catalog_lookup: dict[int, dict[str, Any]] | None = None,
        custom_colors: dict[int, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        if len(sector_ids) > self.sector_limit:
            raise ValueError(f"sector selection exceeds limit {self.sector_limit}")
        existing = {row["id"]: row for row in self.get_sector_configs()}
        lookup = catalog_lookup or {}
        rows: list[dict[str, Any]] = []
        for idx, sid in enumerate(sector_ids):
            prev = existing.get(sid)
            meta = lookup.get(sid) or {}
            code = str(meta.get("sourceCode") or meta.get("code") or (prev or {}).get("sourceCode") or sid)
            name = str(
                meta.get("displayName")
                or meta.get("name")
                or (prev or {}).get("displayName")
                or code
            )
            custom = (custom_colors or {}).get(sid)
            if custom is None and prev:
                custom = prev.get("customColor")
            rows.append(
                {
                    "id": sid,
                    "displayName": name,
                    "sectorType": str((prev or {}).get("sectorType") or meta.get("sectorType") or "HY"),
                    "sourceName": name,
                    "sourceCode": code,
                    "sortOrder": idx,
                    "color": str((prev or {}).get("color") or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]),
                    "customColor": custom,
                }
            )
        self._write_yaml(self.sectors_path, {"sectors": rows})
        return self.get_sector_configs()

    def sector_trend_options(self) -> dict[str, Any]:
        sectors = self.get_sector_configs()
        return {
            "sectors": sectors,
            "selectedSectors": sectors,
            "selectedSectorIds": [s["id"] for s in sectors],
            "sectorBaseLimit": self.sector_limit,
            "sectorExtraLimit": 0,
            "sectorSelectionLimit": self.sector_limit,
            "quotaPackages": [],
        }

    def get_stock_configs(self) -> list[dict[str, Any]]:
        data = self._read_yaml(self.stocks_path)
        rows = data.get("stocks") or []
        out: list[dict[str, Any]] = []
        for idx, row in enumerate(rows):
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                market = str(row.get("market") or "SH")
                code = str(row.get("stockCode") or row.get("code") or "")
                symbol = f"{market}{code}"
            sid = int(row.get("id") or stock_id_from_symbol(symbol))
            market = symbol[:2]
            code = symbol[2:]
            out.append(
                {
                    "id": sid,
                    "stockCode": code,
                    "market": market,
                    "displayName": str(row.get("displayName") or row.get("name") or code),
                    "sourceName": str(row.get("sourceName") or row.get("displayName") or code),
                    "sourceCode": code,
                    "sortOrder": int(row.get("sortOrder") if row.get("sortOrder") is not None else idx),
                    "color": str(row.get("color") or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]),
                    "realtimeFetchEnabled": True,
                    "customColor": row.get("customColor"),
                }
            )
        out.sort(key=lambda x: x["sortOrder"])
        return out

    def set_stock_configs(
        self,
        stock_ids: list[int],
        *,
        catalog_lookup: dict[int, dict[str, Any]] | None = None,
        custom_colors: dict[int, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        if len(stock_ids) > self.stock_limit:
            raise ValueError(f"stock selection exceeds limit {self.stock_limit}")
        existing = {row["id"]: row for row in self.get_stock_configs()}
        lookup = catalog_lookup or {}
        rows: list[dict[str, Any]] = []
        for idx, sid in enumerate(stock_ids):
            prev = existing.get(sid)
            meta = lookup.get(sid) or {}
            symbol = str(meta.get("symbol") or (prev and f"{prev['market']}{prev['stockCode']}") or symbol_from_stock_id(sid))
            market = symbol[:2]
            code = symbol[2:]
            name = str(meta.get("displayName") or meta.get("name") or (prev or {}).get("displayName") or code)
            custom = (custom_colors or {}).get(sid)
            if custom is None and prev:
                custom = prev.get("customColor")
            rows.append(
                {
                    "id": sid,
                    "symbol": symbol,
                    "stockCode": code,
                    "market": market,
                    "displayName": name,
                    "sourceName": name,
                    "sourceCode": code,
                    "sortOrder": idx,
                    "color": str((prev or {}).get("color") or DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]),
                    "customColor": custom,
                }
            )
        self._write_yaml(self.stocks_path, {"stocks": rows})
        return self.get_stock_configs()

    def stock_options_payload(self) -> dict[str, Any]:
        selected = self.get_stock_configs()
        return {
            "stocks": selected,
            "selectedStocks": selected,
            "selectedStockIds": [s["id"] for s in selected],
            "stockAccessEnabled": True,
            "stockBaseLimit": self.stock_limit,
            "stockExtraLimit": 0,
            "stockSelectionLimit": self.stock_limit,
        }
