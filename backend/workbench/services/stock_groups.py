from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from workbench.storage.meta_store import MetaStore

MAX_GROUP_MEMBERS = 50


@dataclass(frozen=True)
class StockGroupMember:
    symbol: str
    name: str


@dataclass(frozen=True)
class StockGroupView:
    id: str
    name: str
    sort_order: int
    symbol_ids: list[str]
    symbols: list[StockGroupMember]


def _new_group_id() -> str:
    return f"stkgrp_{uuid.uuid4().hex[:12]}"


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


class StockGroupService:
    def __init__(self, meta: MetaStore) -> None:
        self._meta = meta

    def ensure_schema(self) -> None:
        with self._meta._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS stock_group (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stock_group_member (
                    group_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (group_id, symbol),
                    FOREIGN KEY (group_id) REFERENCES stock_group(group_id) ON DELETE CASCADE
                );
                """
            )

    def list_groups(self) -> list[StockGroupView]:
        self.ensure_schema()
        with self._meta._session() as connection:
            group_rows = connection.execute(
                "SELECT group_id, name, sort_order FROM stock_group ORDER BY sort_order, created_at"
            ).fetchall()
            member_rows = connection.execute(
                "SELECT group_id, symbol, sort_order FROM stock_group_member ORDER BY sort_order, symbol"
            ).fetchall()
            stock_names = {
                str(row[0]).upper(): str(row[1])
                for row in connection.execute("SELECT symbol, name FROM security_master").fetchall()
            }
        members_by_group: dict[str, list[tuple[str, int]]] = {}
        for group_id, symbol, sort_order in member_rows:
            members_by_group.setdefault(str(group_id), []).append(
                (_normalize_symbol(symbol), int(sort_order))
            )
        views: list[StockGroupView] = []
        for group_id, name, sort_order in group_rows:
            gid = str(group_id)
            ordered = sorted(members_by_group.get(gid, []), key=lambda item: (item[1], item[0]))
            symbol_ids = [symbol for symbol, _ in ordered]
            views.append(
                StockGroupView(
                    id=gid,
                    name=str(name),
                    sort_order=int(sort_order),
                    symbol_ids=symbol_ids,
                    symbols=[
                        StockGroupMember(
                            symbol=symbol,
                            name=stock_names.get(symbol, symbol),
                        )
                        for symbol in symbol_ids
                    ],
                )
            )
        return views

    def read_active_group_id(self) -> str:
        self.ensure_schema()
        with self._meta._session() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='stock_active_group_id'"
            ).fetchone()
        if not row:
            return "all"
        value = str(row[0]).strip()
        return value or "all"

    def set_active_group_id(self, group_id: str) -> str:
        self.ensure_schema()
        normalized = group_id.strip() or "all"
        if normalized != "all":
            exists = any(group.id == normalized for group in self.list_groups())
            if not exists:
                raise ValueError("group not found")
        with self._meta._session() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('stock_active_group_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (normalized,),
            )
        return normalized

    def create_group(self, name: str) -> StockGroupView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("group name must not be blank")
        self.ensure_schema()
        group_id = _new_group_id()
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._meta._session() as connection:
            sort_order = int(
                connection.execute("SELECT COUNT(*) FROM stock_group").fetchone()[0]
            )
            connection.execute(
                "INSERT INTO stock_group(group_id, name, sort_order, created_at) VALUES(?, ?, ?, ?)",
                (group_id, cleaned, sort_order, created_at),
            )
        return self.get_group(group_id)

    def get_group(self, group_id: str) -> StockGroupView:
        for group in self.list_groups():
            if group.id == group_id:
                return group
        raise ValueError("group not found")

    def rename_group(self, group_id: str, name: str) -> StockGroupView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("group name must not be blank")
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute(
                "UPDATE stock_group SET name=? WHERE group_id=?",
                (cleaned, group_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("group not found")
        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> None:
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute("DELETE FROM stock_group WHERE group_id=?", (group_id,))
            if cursor.rowcount == 0:
                raise ValueError("group not found")
        if self.read_active_group_id() == group_id:
            self.set_active_group_id("all")

    def add_members(self, group_id: str, symbols: list[str]) -> StockGroupView:
        self.ensure_schema()
        self.get_group(group_id)
        normalized: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            code = _normalize_symbol(symbol)
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        if not normalized:
            return self.get_group(group_id)
        with self._meta._session() as connection:
            existing = {
                _normalize_symbol(str(row[0]))
                for row in connection.execute(
                    "SELECT symbol FROM stock_group_member WHERE group_id=?",
                    (group_id,),
                ).fetchall()
            }
            new_members = [symbol for symbol in normalized if symbol not in existing]
            if len(existing) + len(new_members) > MAX_GROUP_MEMBERS:
                raise ValueError(f"group member limit is {MAX_GROUP_MEMBERS}")
            next_order = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM stock_group_member WHERE group_id=?",
                    (group_id,),
                ).fetchone()[0]
            )
            for symbol in new_members:
                next_order += 1
                connection.execute(
                    "INSERT INTO stock_group_member(group_id, symbol, sort_order) VALUES(?, ?, ?)",
                    (group_id, symbol, next_order),
                )
        return self.get_group(group_id)

    def remove_member(self, group_id: str, symbol: str) -> StockGroupView:
        self.ensure_schema()
        code = _normalize_symbol(symbol)
        with self._meta._session() as connection:
            connection.execute(
                "DELETE FROM stock_group_member WHERE group_id=? AND symbol=?",
                (group_id, code),
            )
        return self.get_group(group_id)
