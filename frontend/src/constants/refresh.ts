/** Workbench live refresh interval — aligned with Hot Collector (5s). */
export const WORKBENCH_REFRESH_SECONDS = 5
export const WORKBENCH_REFRESH_MS = WORKBENCH_REFRESH_SECONDS * 1000

/** Custom-sector catalog sync interval — aligned with backend directory sync (30s). */
export const CATALOG_REFRESH_SECONDS = 30
export const CATALOG_REFRESH_MS = CATALOG_REFRESH_SECONDS * 1000

/** Hot list live refresh — aligned with backend CACHE_TTL_SECONDS. */
export const HOT_LIST_POLL_SECONDS = 60
export const HOT_LIST_POLL_MS = HOT_LIST_POLL_SECONDS * 1000

/** Hot list off-hours refresh (rankings change slowly outside sessions). */
export const HOT_LIST_OFF_HOURS_POLL_SECONDS = 300
export const HOT_LIST_OFF_HOURS_POLL_MS = HOT_LIST_OFF_HOURS_POLL_SECONDS * 1000

/** Auction board live refresh during 09:15–09:30. */
export const AUCTION_POLL_SECONDS = 10
export const AUCTION_POLL_MS = AUCTION_POLL_SECONDS * 1000
