from workbench.providers.tdx.classic_board_indices import (
    discover_classic_index_ids,
    fetch_classic_index_board_rows,
)


class FakeClassicClient:
    def get_board_summary(self, board_symbol: str) -> dict[str, int]:
        known = {"880490": 137, "880301": 32}
        count = known.get(board_symbol, 0)
        return {"member_count": count}

    def get_stock_quotes(self, stocks: list[tuple[int, str]], fields: object = None) -> list[dict[str, object]]:
        _ = fields
        rows: list[dict[str, object]] = []
        for _market, code in stocks:
            if code == "880490":
                rows.append({"code": "880490", "name": "通信设备"})
            elif code == "880301":
                rows.append({"code": "880301", "name": "煤炭"})
        return rows


def test_discover_classic_index_ids() -> None:
    ids = discover_classic_index_ids(FakeClassicClient().get_board_summary, code_range=range(301, 501))
    assert "880490" in ids
    assert "880301" in ids
    assert "880400" not in ids


def test_fetch_classic_index_board_rows() -> None:
    rows = fetch_classic_index_board_rows(FakeClassicClient())
    by_id = {row["sector_id"]: row for row in rows}
    assert by_id["880490"]["name"] == "通信设备"
    assert by_id["880490"]["sector_type"] == "classic_index"
