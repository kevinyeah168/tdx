from __future__ import annotations

from workbench.query.custom_sector_ids import is_custom_sector_id
from workbench.storage.meta_store import MetaStore


def _name_matched_sector_ids(meta: MetaStore, sector_name: str) -> list[tuple[str, int]]:
    with meta.connect() as connection:
        rows = connection.execute(
            """
            SELECT s.sector_id, COUNT(m.symbol) AS member_count
            FROM sector_master s
            LEFT JOIN sector_membership m ON m.sector_id = s.sector_id
            WHERE s.name = ?
            GROUP BY s.sector_id
            ORDER BY member_count DESC, s.sector_id
            """,
            (sector_name,),
        ).fetchall()
    return [(str(row[0]), int(row[1])) for row in rows if int(row[1]) > 0]


def resolve_member_sector_id(
    meta: MetaStore,
    sector_id: str,
    *,
    sector_name: str | None = None,
) -> str:
    normalized_id = str(sector_id).strip()
    if is_custom_sector_id(normalized_id):
        return normalized_id
    input_count = len(meta.memberships_for(normalized_id))

    if sector_name:
        name = sector_name.strip()
        if name:
            name_matches = _name_matched_sector_ids(meta, name)
            if name_matches:
                best_id, best_count = name_matches[0]
                if best_id != normalized_id and best_count > input_count:
                    return best_id
                if best_id == normalized_id or input_count == 0:
                    return best_id

    if input_count:
        return normalized_id

    if sector_name:
        name = sector_name.strip()
        if name:
            name_matches = _name_matched_sector_ids(meta, name)
            if name_matches:
                return name_matches[0][0]

    if normalized_id.startswith("888"):
        alt_id = "880" + normalized_id[3:]
        if meta.memberships_for(alt_id):
            return alt_id

    return normalized_id
