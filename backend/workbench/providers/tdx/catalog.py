from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from easy_tdx import BoardType, Market

from workbench.config import WorkbenchSettings
from workbench.domain import Membership, Sector, Security
from workbench.providers.base import MarketCatalog
from workbench.providers.tdx.classic_board_indices import fetch_classic_index_board_rows
from workbench.providers.tdx.local_catalog import load_local_security_rows, read_tnf_names
from workbench.providers.tdx.security_cache import load_easy_tdx_security_cache
from workbench.providers.tdx.security_list import (
    ensure_security_cache,
    load_workbench_security_cache,
)
from workbench.providers.tdx.symbols import is_a_share, market_label, normalize_code, to_symbol


def _iter_response_rows(response: object) -> list[object]:
    if response is None:
        return []
    if hasattr(response, "to_dict"):
        records = response.to_dict(orient="records")
        if isinstance(records, list):
            return records
    if isinstance(response, list):
        return response
    if hasattr(response, "__iter__") and not isinstance(response, (str, bytes, dict)):
        return list(response)
    return []


class SecurityListClient(Protocol):
    def get_security_list_all(self, pages: int | str = "all") -> object: ...


class BoardClient(Protocol):
    def get_board_list(self, *, board_type: object, count: int) -> object: ...

    def get_board_members(self, board_symbol: str, *, count: int) -> object: ...


@dataclass(frozen=True, slots=True)
class CatalogLoadResult:
    catalog: MarketCatalog
    source: str
    stale: bool = False
    error_summary: str | None = None


def _canonical_payload(
    securities: list[Security],
    sectors: list[Sector],
    memberships: list[Membership],
) -> str:
    payload = {
        "securities": [security.model_dump(mode="json") for security in securities],
        "sectors": [sector.model_dump(mode="json") for sector in sectors],
        "memberships": [membership.model_dump(mode="json") for membership in memberships],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def catalog_version_for(
    securities: list[Security],
    sectors: list[Sector],
    memberships: list[Membership],
) -> str:
    ordered_securities = sorted(securities, key=lambda item: item.symbol)
    ordered_sectors = sorted(sectors, key=lambda item: item.sector_id)
    ordered_memberships = sorted(memberships, key=lambda item: (item.sector_id, item.symbol))
    digest = hashlib.sha256(
        _canonical_payload(ordered_securities, ordered_sectors, ordered_memberships).encode("utf-8")
    ).hexdigest()
    return f"catalog-{digest[:16]}"


def _parse_security_row(row: dict[str, Any], *, tdx_home: Path | None) -> Security | None:
    market = market_label(row["market"])
    code = normalize_code(str(row["code"]))
    if row.get("active") is False:
        return None
    if not is_a_share(market, code):
        return None
    name = str(row.get("name") or code).strip()
    if tdx_home is not None:
        local_names = read_tnf_names(tdx_home, market)
        if code in local_names:
            name = local_names[code]
    return Security(symbol=to_symbol(market, code), code=code, name=name, market=market)


def _parse_board_rows(rows: list[dict[str, Any]]) -> list[Sector]:
    sectors: list[Sector] = []
    seen: set[str] = set()
    for row in rows:
        sector_id = str(row["sector_id"]).strip()
        if sector_id in seen:
            continue
        seen.add(sector_id)
        sector_type = str(row.get("sector_type") or "industry").strip().lower()
        allowed = {"industry", "concept", "industry2", "style", "region", "classic_index"}
        if sector_type not in allowed:
            sector_type = "industry" if sector_type.startswith("hy") else "concept"
        sectors.append(
            Sector(
                sector_id=sector_id,
                name=str(row["name"]).strip(),
                sector_type=sector_type,
            )
        )
    return sectors


def _parse_memberships(
    rows: list[dict[str, Any]], *, securities: dict[str, Security], sectors: dict[str, Sector]
) -> list[Membership]:
    memberships: list[Membership] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        sector_id = str(row["sector_id"]).strip()
        symbol = str(row["symbol"]).strip().upper()
        if sector_id not in sectors or symbol not in securities:
            continue
        pair = (sector_id, symbol)
        if pair in seen:
            continue
        seen.add(pair)
        memberships.append(Membership(sector_id=sector_id, symbol=symbol))
    return memberships


def build_catalog_from_rows(
    *,
    security_rows: list[dict[str, Any]],
    board_rows: list[dict[str, Any]],
    member_rows: list[dict[str, Any]],
    source: str,
    tdx_home: Path | None = None,
) -> MarketCatalog:
    securities = [
        security
        for row in security_rows
        if (security := _parse_security_row(row, tdx_home=tdx_home)) is not None
    ]
    sectors = _parse_board_rows(board_rows)
    security_map = {security.symbol: security for security in securities}
    sector_map = {sector.sector_id: sector for sector in sectors}
    memberships = _parse_memberships(
        member_rows,
        securities=security_map,
        sectors=sector_map,
    )
    version = catalog_version_for(securities, sectors, memberships)
    return MarketCatalog(
        securities=securities,
        sectors=sectors,
        memberships=memberships,
        version=version,
    )


class TdxCatalogLoader:
    def __init__(
        self,
        *,
        security_rows: list[dict[str, Any]] | None = None,
        board_rows: list[dict[str, Any]] | None = None,
        member_rows: list[dict[str, Any]] | None = None,
        normal_client: SecurityListClient | None = None,
        enhanced_client: BoardClient | None = None,
        tdx_home: Path | None = None,
        source: str = "tdx.network",
        board_page_size: int = 500,
        settings: WorkbenchSettings | None = None,
    ) -> None:
        self._security_rows = security_rows
        self._board_rows = board_rows
        self._member_rows = member_rows
        self._normal_client = normal_client
        self._enhanced_client = enhanced_client
        self._tdx_home = tdx_home
        self._source = source
        self._board_page_size = board_page_size
        self._settings = settings

    @classmethod
    def from_fixture_dir(cls, fixture_dir: Path) -> "TdxCatalogLoader":
        return cls(
            security_rows=json.loads((fixture_dir / "security_list.json").read_text(encoding="utf-8")),
            board_rows=json.loads((fixture_dir / "boards.json").read_text(encoding="utf-8")),
            member_rows=json.loads((fixture_dir / "board_members.json").read_text(encoding="utf-8")),
            source="tdx.fixture",
        )

    def load(self) -> CatalogLoadResult:
        try:
            security_rows = self._security_rows or self._fetch_security_rows()
            board_rows = self._board_rows or self._fetch_board_rows()
            member_rows = self._member_rows or self._fetch_member_rows(board_rows)
            catalog = build_catalog_from_rows(
                security_rows=security_rows,
                board_rows=board_rows,
                member_rows=member_rows,
                source=self._source,
                tdx_home=self._tdx_home,
            )
            return CatalogLoadResult(catalog=catalog, source=self._source)
        except Exception as error:
            return CatalogLoadResult(
                catalog=MarketCatalog(securities=[], sectors=[], memberships=[], version="catalog-empty"),
                source=self._source,
                stale=True,
                error_summary=str(error),
            )

    def _fetch_security_rows(self) -> list[dict[str, Any]]:
        if self._settings is not None:
            cached = load_workbench_security_cache(self._settings)
            if cached:
                return cached
            try:
                return ensure_security_cache(self._settings)
            except Exception as error:
                log = __import__("logging").getLogger(__name__)
                log.warning("resilient security fetch failed: %s", error)
        cached_rows = load_easy_tdx_security_cache()
        if cached_rows:
            return [
                {
                    "market": row["market"],
                    "code": row["code"],
                    "name": row["name"],
                    "active": is_a_share(row["market"], row["code"]),
                }
                for row in cached_rows
            ]
        if self._normal_client is None:
            raise ValueError("security rows require a normal client, easy_tdx cache, or fixture data")
        raw_rows = self._normal_client.get_security_list_all(pages="all")
        rows: list[dict[str, Any]] = []
        for row in _iter_response_rows(raw_rows):
            market = market_label(getattr(row, "market", row.get("market")))
            code = normalize_code(str(getattr(row, "code", row.get("code"))))
            name = str(getattr(row, "name", row.get("name", code))).strip()
            rows.append({"market": market, "code": code, "name": name, "active": is_a_share(market, code)})
        return rows

    def _fetch_board_rows(self) -> list[dict[str, Any]]:
        if self._enhanced_client is None:
            raise ValueError("board rows require an enhanced client or fixture data")
        rows: list[dict[str, Any]] = []
        for board_type, sector_type in (
            (BoardType.HY, "industry"),
            (BoardType.GN, "concept"),
            (BoardType.HY2, "industry2"),
            (BoardType.FG, "style"),
            (BoardType.DQ, "region"),
        ):
            raw_boards = self._enhanced_client.get_board_list(
                board_type=board_type,
                count=self._board_page_size,
            )
            for board in _iter_response_rows(raw_boards):
                sector_id = str(
                    getattr(board, "code", None)
                    or (board.get("code") if isinstance(board, dict) else None)
                    or getattr(board, "sector_id", None)
                    or (board.get("sector_id") if isinstance(board, dict) else "")
                ).strip()
                name = str(getattr(board, "name", board.get("name", sector_id))).strip()
                rows.append({"sector_id": sector_id, "name": name, "sector_type": sector_type})
        existing = {str(row["sector_id"]) for row in rows}
        if self._enhanced_client is not None and hasattr(self._enhanced_client, "get_board_summary"):
            for classic in fetch_classic_index_board_rows(self._enhanced_client):
                sector_id = str(classic["sector_id"])
                if sector_id in existing:
                    continue
                rows.append(classic)
                existing.add(sector_id)
        return rows

    def _fetch_member_rows(self, board_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._enhanced_client is None:
            raise ValueError("member rows require an enhanced client or fixture data")
        memberships: list[dict[str, Any]] = []
        for board in board_rows:
            sector_id = str(board["sector_id"])
            raw_members = self._enhanced_client.get_board_members(
                sector_id,
                count=self._board_page_size,
            )
            for member in _iter_response_rows(raw_members):
                symbol = getattr(member, "symbol", None) or (
                    member.get("symbol") if isinstance(member, dict) else None
                )
                if symbol:
                    memberships.append(
                        {
                            "sector_id": sector_id,
                            "symbol": str(symbol).strip().upper(),
                        }
                    )
                    continue
                market = getattr(member, "market", member.get("market", Market.SH) if isinstance(member, dict) else Market.SH)
                if isinstance(market, int):
                    market = Market(market)
                code = normalize_code(str(getattr(member, "code", member.get("code") if isinstance(member, dict) else "")))
                memberships.append(
                    {
                        "sector_id": sector_id,
                        "symbol": to_symbol(market_label(market), code),
                    }
                )
        return memberships
