from __future__ import annotations

from workbench.config import WorkbenchSettings
from workbench.providers.base import MarketDataProvider
from workbench.providers.tdx.security_list import ensure_security_cache
from workbench.storage.history_store import HistoryStore


class HistorySyncService:
    def __init__(self, provider: MarketDataProvider, settings: WorkbenchSettings) -> None:
        self._provider = provider
        self._settings = settings
        self._history = HistoryStore(settings.data_dir / "history" / "bars.sqlite")
        self._history.initialize()

    def sync_symbols(self, symbols: list[str], *, count: int = 120) -> dict[str, int]:
        if not hasattr(self._provider, "bars"):
            return {"synced": 0, "requested": len(symbols)}
        synced = 0
        for symbol in symbols:
            envelope = self._provider.bars(symbol, "day", count)
            if envelope.data is None or not envelope.data:
                continue
            self._history.replace_bars(
                symbol=symbol,
                period="day",
                bars=envelope.data,
                source=envelope.source,
            )
            synced += 1
        return {"synced": synced, "requested": len(symbols)}


def refresh_security_cache(settings: WorkbenchSettings, *, force: bool) -> int:
    rows = ensure_security_cache(settings, force=force)
    return len(rows)
