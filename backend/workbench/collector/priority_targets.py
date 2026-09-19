from __future__ import annotations

from collections.abc import Iterable

from workbench.collector.priority_linkage import read_linkage_sector_id, read_linkage_sector_name
from workbench.collector.priority_sectors import read_priority_sector_ids
from workbench.collector.priority_stocks import (
    read_priority_manual_symbols,
    write_priority_stock_targets,
)
from workbench.config import WorkbenchSettings
from workbench.query.sector_resolve import resolve_member_sector_id
from workbench.storage.meta_store import MetaStore


def merge_unique_ids(items: Iterable[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in items:
        code = str(item).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append(code)
        if len(merged) >= limit:
            break
    return merged


def merge_priority_sector_ids(
    *,
    selected: Iterable[str],
    ranked: Iterable[str],
    linkage_sector_id: str | None,
    max_sectors: int,
) -> list[str]:
    linkage = str(linkage_sector_id or "").strip()
    ordered: list[str] = []
    if linkage:
        ordered.append(linkage)
    ordered.extend(selected)
    ordered.extend(ranked)
    return merge_unique_ids(ordered, limit=max(1, max_sectors))


def sector_member_symbols(
    meta: MetaStore,
    sector_id: str,
    *,
    per_sector_limit: int,
    enhanced_client: object | None = None,
    sector_name: str | None = None,
) -> list[str]:
    from workbench.query.custom_sector_ids import is_custom_sector_id
    from workbench.services.custom_sectors import CustomSectorService

    resolved = resolve_member_sector_id(meta, sector_id, sector_name=sector_name)
    limit = max(1, int(per_sector_limit))
    if is_custom_sector_id(resolved):
        return CustomSectorService(meta).symbols_for(resolved)[:limit]
    catalog = meta.memberships_for(resolved)
    # Prefer full catalog membership when available so "自选板块" keeps every constituent.
    if catalog:
        return catalog[:limit]
    if enhanced_client is not None:
        from workbench.providers.tdx.live_members import fetch_live_board_members

        live_rows = fetch_live_board_members(
            enhanced_client,
            resolved,
            limit=limit,
            member_count=limit,
        )
        return [str(row["symbol"]) for row in live_rows]
    return []


def resolve_priority_stock_symbols(
    meta: MetaStore,
    settings: WorkbenchSettings,
    *,
    sector_ids: Iterable[str],
    linkage_sector_id: str | None = None,
    linkage_sector_name: str | None = None,
    manual_symbols: Iterable[str],
    enhanced_client: object | None = None,
) -> list[str]:
    ordered: list[str] = []
    linkage = str(linkage_sector_id or "").strip()
    if linkage:
        ordered.extend(
            sector_member_symbols(
                meta,
                linkage,
                per_sector_limit=settings.priority_linkage_members,
                enhanced_client=enhanced_client,
                sector_name=linkage_sector_name,
            )
        )
    for sector_id in sector_ids:
        ordered.extend(
            sector_member_symbols(
                meta,
                sector_id,
                per_sector_limit=settings.priority_sector_members,
                enhanced_client=enhanced_client,
            )
        )
    ordered.extend(manual_symbols)
    return merge_unique_ids(ordered, limit=settings.priority_max_stocks)


def resolve_linkage_sector_id(meta: MetaStore, settings: WorkbenchSettings) -> str | None:
    linkage_id = read_linkage_sector_id(settings.data_dir)
    if not linkage_id:
        return None
    return resolve_member_sector_id(
        meta,
        linkage_id,
        sector_name=read_linkage_sector_name(settings.data_dir),
    )


def apply_hot_target_sync(
    settings: WorkbenchSettings,
    meta: MetaStore,
    *,
    selected_sector_ids: Iterable[str],
    rank_sector_ids: Iterable[str],
    selected_stock_symbols: Iterable[str],
    linkage_sector_id: str | None = None,
    linkage_sector_name: str | None = None,
    enhanced_client: object | None = None,
) -> dict[str, int | str]:
    from workbench.collector.priority_linkage import write_linkage_sector_id
    from workbench.collector.priority_sectors import write_priority_sector_ids

    resolved_linkage = None
    if linkage_sector_id:
        resolved_linkage = resolve_member_sector_id(
            meta,
            linkage_sector_id,
            sector_name=linkage_sector_name,
        )
    elif read_linkage_sector_id(settings.data_dir):
        resolved_linkage = resolve_linkage_sector_id(meta, settings)

    merged_sectors = merge_priority_sector_ids(
        selected=selected_sector_ids,
        ranked=rank_sector_ids,
        linkage_sector_id=resolved_linkage,
        max_sectors=settings.priority_max_sectors,
    )
    manual_symbols = [str(symbol).strip().upper() for symbol in selected_stock_symbols if str(symbol).strip()]
    merged_stocks = resolve_priority_stock_symbols(
        meta,
        settings,
        sector_ids=merged_sectors,
        linkage_sector_id=resolved_linkage,
        linkage_sector_name=linkage_sector_name or read_linkage_sector_name(settings.data_dir),
        manual_symbols=manual_symbols,
        enhanced_client=enhanced_client,
    )
    write_priority_sector_ids(settings.data_dir, merged_sectors)
    write_priority_stock_targets(settings.data_dir, manual_symbols, merged_stocks)
    if linkage_sector_id is not None:
        write_linkage_sector_id(
            settings.data_dir,
            linkage_sector_id or None,
            sector_name=linkage_sector_name,
        )
    return {
        "sectors": len(merged_sectors),
        "stocks": len(merged_stocks),
        "linkage_sector_id": resolved_linkage or "",
    }


def refresh_priority_stock_targets(
    settings: WorkbenchSettings,
    meta: MetaStore,
    *,
    enhanced_client: object | None = None,
) -> list[str]:
    """Recompute resolved stock targets from current sector/linkage/manual files."""
    resolved_linkage = resolve_linkage_sector_id(meta, settings)
    merged_stocks = resolve_priority_stock_symbols(
        meta,
        settings,
        sector_ids=read_priority_sector_ids(settings.data_dir),
        linkage_sector_id=resolved_linkage,
        linkage_sector_name=read_linkage_sector_name(settings.data_dir),
        manual_symbols=read_priority_manual_symbols(settings.data_dir),
        enhanced_client=enhanced_client,
    )
    write_priority_stock_targets(
        settings.data_dir,
        read_priority_manual_symbols(settings.data_dir),
        merged_stocks,
    )
    return merged_stocks
