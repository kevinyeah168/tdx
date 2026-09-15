from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from easy_tdx import TdxClient
from easy_tdx.models.enums import Market
from easy_tdx.transport.sync import ping_all

from workbench.config import WorkbenchSettings
from workbench.providers.tdx.symbols import is_a_share, market_label, normalize_code, to_symbol
from workbench.providers.tdx.text_clean import clean_tdx_text

log = logging.getLogger(__name__)

_PAGE_SIZE = 1000
_MARKETS = (Market.SH, Market.SZ, Market.BJ)


def cache_path(settings: WorkbenchSettings) -> Path:
    return settings.data_dir / "meta" / "security_list_cache.json"


def load_workbench_security_cache(settings: WorkbenchSettings) -> list[dict[str, Any]] | None:
    path = cache_path(settings)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    return rows


def save_workbench_security_cache(settings: WorkbenchSettings, rows: list[dict[str, Any]]) -> None:
    path = cache_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _best_host() -> str:
    ranked = ping_all(timeout=3.0)
    if not ranked:
        raise RuntimeError("no reachable TDX normal hosts")
    return str(ranked[0][0])


def _fetch_page(host: str, market: Market, start: int, *, timeout: float) -> list[Any]:
    client = TdxClient(host=host, port=7709, timeout=timeout, auto_reconnect=False)
    client.connect()
    try:
        frame = client.get_security_list(market, start)
        return frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
    finally:
        client.close()


def fetch_security_rows_resilient(
    *,
    timeout_seconds: float = 30.0,
    page_pause_seconds: float = 0.15,
    max_pages_per_market: int | None = None,
) -> list[dict[str, Any]]:
    host = _best_host()
    log.info("fetching security list via %s with reconnect-per-page", host)
    rows: list[dict[str, Any]] = []
    for market in _MARKETS:
        try:
            rows.extend(
                _fetch_market_rows(
                    host,
                    market,
                    timeout_seconds=timeout_seconds,
                    page_pause_seconds=page_pause_seconds,
                    max_pages_per_market=max_pages_per_market,
                )
            )
        except Exception as error:
            if market is Market.BJ:
                log.warning("BJ security list unavailable, continuing without BJ: %s", error)
                continue
            raise
    if not rows:
        raise RuntimeError("security list fetch returned zero A-share rows")
    return rows


def _fetch_market_rows(
    host: str,
    market: Market,
    *,
    timeout_seconds: float,
    page_pause_seconds: float,
    max_pages_per_market: int | None,
) -> list[dict[str, Any]]:
    count_client = TdxClient(host=host, port=7709, timeout=timeout_seconds, auto_reconnect=False)
    count_client.connect()
    try:
        total_count = int(count_client.get_security_count(market))
    finally:
        count_client.close()
    limit = total_count
    if max_pages_per_market is not None:
        limit = min(limit, max_pages_per_market * _PAGE_SIZE)
    total_pages = max(1, (limit + _PAGE_SIZE - 1) // _PAGE_SIZE)
    market_rows: list[dict[str, Any]] = []
    for page_index, start in enumerate(range(0, limit, _PAGE_SIZE)):
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                page_rows = _fetch_page(host, market, start, timeout=timeout_seconds)
                log.info(
                    "%s page %d/%d -> %d rows",
                    market.name,
                    page_index + 1,
                    total_pages,
                    len(page_rows),
                )
                break
            except Exception as error:
                last_error = error
                log.warning(
                    "%s page %d attempt %d failed: %s",
                    market.name,
                    page_index + 1,
                    attempt + 1,
                    error,
                )
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RuntimeError(
                f"{market.name} page {page_index + 1} failed after retries"
            ) from last_error
        label = market_label(market)
        for row in page_rows:
            code = normalize_code(str(row.get("code", "")))
            if not is_a_share(label, code):
                continue
            name = clean_tdx_text(row.get("name") or code, fallback=code)
            market_rows.append({"market": label, "code": code, "name": name, "active": True})
        time.sleep(page_pause_seconds)
    return market_rows


def ensure_security_cache(settings: WorkbenchSettings, *, force: bool = False) -> list[dict[str, Any]]:
    if not force:
        cached = load_workbench_security_cache(settings)
        if cached:
            return cached
    from workbench.providers.tdx.security_cache import load_easy_tdx_security_cache

    easy_rows = load_easy_tdx_security_cache()
    if easy_rows and not force:
        save_workbench_security_cache(settings, easy_rows)
        return easy_rows
    rows = fetch_security_rows_resilient()
    save_workbench_security_cache(settings, rows)
    return rows
