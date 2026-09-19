from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from workbench.services.custom_sectors import CustomSectorService
from workbench.storage.meta_store import MetaStore

MAX_GROUP_MEMBERS = 60
MAX_CHART_VISIBLE = 60


@dataclass(frozen=True)
class SectorGroupMember:
    sector_id: str
    name: str
    chart_visible: bool = True


@dataclass(frozen=True)
class SectorGroupView:
    id: str
    name: str
    sort_order: int
    sector_ids: list[str]
    sectors: list[SectorGroupMember]


def _new_group_id() -> str:
    return f"grp_{uuid.uuid4().hex[:12]}"


class SectorGroupService:
    def __init__(self, meta: MetaStore) -> None:
        self._meta = meta

    def ensure_schema(self) -> None:
        with self._meta._session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sector_group (
                    group_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sector_group_member (
                    group_id TEXT NOT NULL,
                    sector_id TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    chart_visible INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (group_id, sector_id),
                    FOREIGN KEY (group_id) REFERENCES sector_group(group_id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(sector_group_member)").fetchall()
            }
            if "chart_visible" not in columns:
                connection.execute(
                    "ALTER TABLE sector_group_member "
                    "ADD COLUMN chart_visible INTEGER NOT NULL DEFAULT 1"
                )

    def list_groups(self) -> list[SectorGroupView]:
        self.ensure_schema()
        with self._meta._session() as connection:
            group_rows = connection.execute(
                "SELECT group_id, name, sort_order FROM sector_group ORDER BY sort_order, created_at"
            ).fetchall()
            member_rows = connection.execute(
                "SELECT group_id, sector_id, sort_order, chart_visible "
                "FROM sector_group_member ORDER BY sort_order, sector_id"
            ).fetchall()
            sector_names = {
                str(row[0]): str(row[1])
                for row in connection.execute("SELECT sector_id, name FROM sector_master").fetchall()
            }
            sector_names.update(CustomSectorService(self._meta).sector_names())
        members_by_group: dict[str, list[tuple[str, int, bool]]] = {}
        for group_id, sector_id, sort_order, chart_visible in member_rows:
            members_by_group.setdefault(str(group_id), []).append(
                (str(sector_id), int(sort_order), bool(int(chart_visible)))
            )
        views: list[SectorGroupView] = []
        for group_id, name, sort_order in group_rows:
            gid = str(group_id)
            ordered = sorted(members_by_group.get(gid, []), key=lambda item: (item[1], item[0]))
            sector_ids = [sector_id for sector_id, _, _ in ordered]
            views.append(
                SectorGroupView(
                    id=gid,
                    name=str(name),
                    sort_order=int(sort_order),
                    sector_ids=sector_ids,
                    sectors=[
                        SectorGroupMember(
                            sector_id=sector_id,
                            name=sector_names.get(sector_id, sector_id),
                            chart_visible=chart_visible,
                        )
                        for sector_id, _, chart_visible in ordered
                    ],
                )
            )
        return views

    def read_active_group_id(self) -> str:
        self.ensure_schema()
        with self._meta._session() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='sector_active_group_id'"
            ).fetchone()
        if not row:
            return "all"
        value = str(row[0]).strip()
        return value or "all"

    def resolve_active_group_id(self) -> str | None:
        """Return a concrete group id for homepage display, or None if no groups."""
        active = self.read_active_group_id()
        groups = self.list_groups()
        if not groups:
            return None
        if active != "all" and any(group.id == active for group in groups):
            return active
        first = groups[0]
        self.set_active_group_id(first.id)
        return first.id

    def set_active_group_id(self, group_id: str) -> str:
        self.ensure_schema()
        normalized = group_id.strip() or "all"
        if normalized != "all":
            exists = any(group.id == normalized for group in self.list_groups())
            if not exists:
                raise ValueError("group not found")
        with self._meta._session() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES('sector_active_group_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (normalized,),
            )
        return normalized

    def create_group(self, name: str) -> SectorGroupView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("group name must not be blank")
        self.ensure_schema()
        group_id = _new_group_id()
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._meta._session() as connection:
            sort_order = int(
                connection.execute("SELECT COUNT(*) FROM sector_group").fetchone()[0]
            )
            connection.execute(
                "INSERT INTO sector_group(group_id, name, sort_order, created_at) VALUES(?, ?, ?, ?)",
                (group_id, cleaned, sort_order, created_at),
            )
        return self.get_group(group_id)

    def get_group(self, group_id: str) -> SectorGroupView:
        for group in self.list_groups():
            if group.id == group_id:
                return group
        raise ValueError("group not found")

    def rename_group(self, group_id: str, name: str) -> SectorGroupView:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("group name must not be blank")
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute(
                "UPDATE sector_group SET name=? WHERE group_id=?",
                (cleaned, group_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("group not found")
        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> None:
        self.ensure_schema()
        with self._meta._session() as connection:
            cursor = connection.execute("DELETE FROM sector_group WHERE group_id=?", (group_id,))
            if cursor.rowcount == 0:
                raise ValueError("group not found")
        if self.read_active_group_id() == group_id:
            self.set_active_group_id("all")

    def add_members(self, group_id: str, sector_ids: list[str]) -> SectorGroupView:
        self.ensure_schema()
        self.get_group(group_id)
        normalized = []
        seen: set[str] = set()
        for sector_id in sector_ids:
            code = str(sector_id).strip()
            if not code or code in seen:
                continue
            seen.add(code)
            normalized.append(code)
        if not normalized:
            return self.get_group(group_id)
        with self._meta._session() as connection:
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT sector_id FROM sector_group_member WHERE group_id=?",
                    (group_id,),
                ).fetchall()
            }
            new_members = [sector_id for sector_id in normalized if sector_id not in existing]
            if len(existing) + len(new_members) > MAX_GROUP_MEMBERS:
                raise ValueError(f"group member limit is {MAX_GROUP_MEMBERS}")
            next_order = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM sector_group_member WHERE group_id=?",
                    (group_id,),
                ).fetchone()[0]
            )
            for sector_id in new_members:
                next_order += 1
                connection.execute(
                    "INSERT INTO sector_group_member(group_id, sector_id, sort_order, chart_visible) "
                    "VALUES(?, ?, ?, 1)",
                    (group_id, sector_id, next_order),
                )
        return self.get_group(group_id)

    def remove_member(self, group_id: str, sector_id: str) -> SectorGroupView:
        self.ensure_schema()
        with self._meta._session() as connection:
            connection.execute(
                "DELETE FROM sector_group_member WHERE group_id=? AND sector_id=?",
                (group_id, sector_id),
            )
        return self.get_group(group_id)

    def set_member_chart_visible(
        self,
        group_id: str,
        sector_id: str,
        visible: bool,
    ) -> SectorGroupView:
        self.ensure_schema()
        self.get_group(group_id)
        code = str(sector_id).strip()
        if not code:
            raise ValueError("sector_id must not be blank")
        with self._meta._session() as connection:
            row = connection.execute(
                "SELECT chart_visible FROM sector_group_member WHERE group_id=? AND sector_id=?",
                (group_id, code),
            ).fetchone()
            if row is None:
                raise ValueError("member not found")
            currently_visible = bool(int(row[0]))
            if visible and not currently_visible:
                visible_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sector_group_member "
                        "WHERE group_id=? AND chart_visible=1",
                        (group_id,),
                    ).fetchone()[0]
                )
                if visible_count >= MAX_CHART_VISIBLE:
                    raise ValueError(f"chart visible limit is {MAX_CHART_VISIBLE}")
            connection.execute(
                "UPDATE sector_group_member SET chart_visible=? WHERE group_id=? AND sector_id=?",
                (1 if visible else 0, group_id, code),
            )
        return self.get_group(group_id)
