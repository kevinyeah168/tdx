from __future__ import annotations

CUSTOM_SECTOR_PREFIX = "custom_"
CUSTOM_SECTOR_TYPE = "custom"


def is_custom_sector_id(sector_id: str) -> bool:
    return str(sector_id or "").strip().startswith(CUSTOM_SECTOR_PREFIX)
