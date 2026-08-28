from __future__ import annotations

from typing import Any, Callable, Iterable, Protocol

from easy_tdx import Market

from workbench.providers.tdx.symbols import market_label, normalize_code, to_symbol


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


# 通达信 APP「板块指数」常用 8803xx–8805xx；MAC get_board_list 不枚举，但可查询。
CLASSIC_INDEX_PREFIX = "880"
CLASSIC_INDEX_RANGE = range(300, 560)


class ClassicIndexClient(Protocol):
    def get_board_summary(self, board_symbol: str) -> object: ...

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> object: ...


def _summary_member_count(summary: object) -> int:
    if isinstance(summary, dict):
        return int(summary.get("member_count") or 0)
    return int(getattr(summary, "member_count", 0) or 0)


def _quote_name(row: object) -> str:
    if isinstance(row, dict):
        return str(row.get("name") or "").strip()
    return str(getattr(row, "name", "") or "").strip()


def discover_classic_index_ids(
    get_board_summary: Callable[[str], object],
    *,
    code_range: Iterable[int] = CLASSIC_INDEX_RANGE,
) -> list[str]:
    sector_ids: list[str] = []
    for serial in code_range:
        sector_id = f"{CLASSIC_INDEX_PREFIX}{serial:03d}"
        try:
            summary = get_board_summary(sector_id)
        except Exception:
            continue
        if _summary_member_count(summary) > 0:
            sector_ids.append(sector_id)
    return sector_ids


def fetch_classic_index_board_rows(client: ClassicIndexClient) -> list[dict[str, Any]]:
    sector_ids = discover_classic_index_ids(client.get_board_summary)
    if not sector_ids:
        return []

    names: dict[str, str] = {}
    batch_size = 80
    for offset in range(0, len(sector_ids), batch_size):
        batch = sector_ids[offset : offset + batch_size]
        quotes = client.get_stock_quotes([(1, sector_id) for sector_id in batch])
        for row in _iter_response_rows(quotes):
            code = str(
                getattr(row, "code", None)
                or (row.get("code") if isinstance(row, dict) else "")
            ).strip()
            name = _quote_name(row)
            if code and name:
                names[code] = name

    rows: list[dict[str, Any]] = []
    for sector_id in sector_ids:
        rows.append(
            {
                "sector_id": sector_id,
                "name": names.get(sector_id, f"板块指数{sector_id}"),
                "sector_type": "classic_index",
            }
        )
    return rows


def members_from_board_summary(summary: object, *, sector_id: str) -> list[dict[str, str]]:
    members = summary.get("members") if isinstance(summary, dict) else getattr(summary, "members", None)
    if members is None:
        return []
    rows: list[dict[str, str]] = []
    for member in _iter_response_rows(members):
        market = getattr(member, "market", member.get("market", Market.SH) if isinstance(member, dict) else Market.SH)
        if isinstance(market, int):
            market = Market(market)
        code = normalize_code(
            str(getattr(member, "code", member.get("code") if isinstance(member, dict) else ""))
        )
        if not code:
            continue
        rows.append(
            {
                "sector_id": sector_id,
                "symbol": to_symbol(market_label(market), code),
            }
        )
    return rows
