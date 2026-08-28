from __future__ import annotations

from workbench.storage.hot_store import HotStore


class GapRepairService:
    def __init__(self, hot: HotStore) -> None:
        self._hot = hot

    def record(
        self,
        entity_type: str,
        entity_id: str,
        trade_date: str,
        minute: str,
        reason: str,
    ) -> None:
        self._hot.record_gap(
            entity_type=entity_type,
            entity_id=entity_id,
            trade_date=trade_date,
            minute=minute,
            reason=reason,
        )

    def list_unresolved(self, trade_date: str) -> list[dict[str, str | int]]:
        return self._hot.unresolved_gaps(trade_date)

    def resolve(self, entity_type: str, entity_id: str, trade_date: str, minute: str) -> None:
        self._hot.resolve_gap(
            entity_type=entity_type,
            entity_id=entity_id,
            trade_date=trade_date,
            minute=minute,
        )
