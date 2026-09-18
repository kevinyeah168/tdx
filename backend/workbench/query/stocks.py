from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from workbench.domain import BarPeriod
from workbench.providers.tdx.text_clean import clean_tdx_text
from workbench.query.models import QueryMetadata, StockRankItem, StockRankResponse
from workbench.storage.history_store import HistoryStore
from workbench.storage.hot_store import HotStore
from workbench.storage.meta_store import MetaStore


class StockQueryService:
    def __init__(
        self,
        meta: MetaStore,
        hot: HotStore | None = None,
        history: HistoryStore | None = None,
    ) -> None:
        self._meta = meta
        self._hot = hot
        self._history = history

    def security(self, symbol: str) -> dict[str, object] | None:
        normalized = symbol.upper()
        with self._meta.connect() as connection:
            row = connection.execute(
                "SELECT symbol, code, name, market, active FROM security_master WHERE symbol=?",
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        snapshot = self._meta.catalog_snapshot()
        return {
            "symbol": str(row[0]),
            "code": str(row[1]),
            "name": str(row[2]),
            "market": str(row[3]),
            "active": bool(row[4]),
            "metadata": QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
            ).model_dump(mode="json"),
        }

    def _all_security_names(self) -> dict[str, str]:
        with self._meta.connect() as connection:
            rows = connection.execute("SELECT symbol, name FROM security_master").fetchall()
        return {
            str(row[0]): clean_tdx_text(row[1], fallback=str(row[0]))
            for row in rows
        }

    def resolve_symbols(self, inputs: list[str]) -> dict[str, object]:
        names = self._all_security_names()
        symbol_set = set(names)
        resolved: list[dict[str, str]] = []
        unresolved: list[str] = []
        seen: set[str] = set()
        prefixed = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
        digits = re.compile(r"^\d{6}$")

        for raw in inputs:
            token = str(raw).strip().upper()
            if not token:
                continue
            candidate: str | None = None
            if prefixed.fullmatch(token):
                candidate = token if token in symbol_set else None
            elif digits.fullmatch(token):
                for prefix in ("SH", "SZ", "BJ"):
                    symbol = f"{prefix}{token}"
                    if symbol in symbol_set:
                        candidate = symbol
                        break
            else:
                code_matches = [symbol for symbol in symbol_set if token in symbol]
                name_matches = [
                    symbol for symbol, name in names.items() if token in name.upper()
                ]
                matches = sorted(set(code_matches + name_matches))
                if len(matches) == 1:
                    candidate = matches[0]

            if candidate and candidate not in seen:
                seen.add(candidate)
                resolved.append({"symbol": candidate, "name": names[candidate]})
            else:
                unresolved.append(str(raw).strip())

        return {"resolved": resolved, "unresolved": unresolved}

    def stock_ranking(self, trade_date: str, minute: str) -> StockRankResponse:
        snapshot = self._meta.catalog_snapshot()
        names = self._all_security_names()
        metadata = QueryMetadata(
            catalog_version=snapshot.catalog_version,
            stale=snapshot.stale,
            source=snapshot.source,
        )
        if self._hot is None:
            items = [
                StockRankItem(
                    symbol=symbol,
                    name=name,
                    main_cumulative=0.0,
                    change_pct=0.0,
                )
                for symbol, name in sorted(names.items())
            ]
            return StockRankResponse(
                trade_date=trade_date,
                minute=minute,
                items=items,
                metadata=metadata,
            )

        effective_minute = minute
        rows: list[tuple[str, float, float]] = []
        for candidate in (
            minute,
            self._hot.latest_stock_minute(trade_date),
            self._hot.latest_complete_minute(trade_date),
        ):
            if not candidate:
                continue
            with self._hot.connect(readonly=True) as connection:
                fetched = connection.execute(
                    """
                    SELECT symbol, main_cum, change_pct
                    FROM stock_minute
                    WHERE trade_date = ? AND minute = ?
                    ORDER BY main_cum DESC, symbol
                    """,
                    (trade_date, candidate),
                ).fetchall()
            if fetched:
                effective_minute = str(candidate)
                rows = [(str(row[0]), float(row[1]), float(row[2])) for row in fetched]
                break

        if not rows:
            items = [
                StockRankItem(
                    symbol=symbol,
                    name=name,
                    main_cumulative=0.0,
                    change_pct=0.0,
                )
                for symbol, name in sorted(names.items())
            ]
            return StockRankResponse(
                trade_date=trade_date,
                minute=minute,
                items=items,
                metadata=metadata,
            )

        items = [
            StockRankItem(
                symbol=symbol,
                name=names.get(symbol, symbol),
                main_cumulative=main_cum,
                change_pct=change_pct,
            )
            for symbol, main_cum, change_pct in rows
        ]
        return StockRankResponse(
            trade_date=trade_date,
            minute=effective_minute,
            items=items,
            metadata=QueryMetadata(
                catalog_version=snapshot.catalog_version,
                stale=snapshot.stale,
                source=snapshot.source,
                batch_id=f"{trade_date}T{effective_minute}",
            ),
        )

    def sectors_for(self, symbol: str) -> list[dict[str, str]]:
        normalized = symbol.upper()
        with self._meta.connect() as connection:
            rows = connection.execute(
                "SELECT s.sector_id, s.name, s.sector_type "
                "FROM sector_membership m "
                "INNER JOIN sector_master s ON s.sector_id = m.sector_id "
                "WHERE m.symbol=? ORDER BY s.sector_id",
                (normalized,),
            ).fetchall()
        return [
            {"sector_id": str(row[0]), "name": str(row[1]), "sector_type": str(row[2])}
            for row in rows
        ]

    def intraday(self, symbol: str, trade_date: str) -> list[dict[str, object]]:
        if self._hot is None:
            return []
        normalized = symbol.upper()
        rows = self._hot.live_stock_fund_curve(trade_date, normalized).rows
        return [
            {
                "minute": str(row["minute"]),
                "close": float(row["close"]),
                "change_pct": float(row["change_pct"]),
                "main_cumulative": float(row["main_cum"]),
            }
            for row in rows
            if row.get("close") is not None
        ]

    def bars(self, symbol: str, period: BarPeriod, count: int) -> tuple[list[dict[str, object]], str | None]:
        if self._history is None:
            return [], "history cache unavailable"
        normalized = symbol.upper()
        bars = self._history.fetch_bars(normalized, period, count)
        if not bars:
            return [], "bars not synced for symbol"
        return [
            {
                "timestamp": bar.timestamp.isoformat(sep=" ", timespec="minutes"),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "amount": bar.amount,
            }
            for bar in bars
        ], None


class ReplayQueryService:
    def __init__(self, settings_data_dir: Path, meta: MetaStore, hot: HotStore | None = None) -> None:
        self._data_dir = settings_data_dir
        self._meta = meta
        self._hot = hot

    def available_dates(self) -> list[str]:
        hot_dir = self._data_dir / "hot"
        if not hot_dir.is_dir():
            return []
        dates: list[str] = []
        for path in sorted(hot_dir.glob("*.sqlite")):
            try:
                trade_day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if trade_day.weekday() >= 5:
                continue
            dates.append(path.stem)
        return dates

    def complete_minutes(self, trade_date: str) -> list[str]:
        if self._hot is None:
            return []
        return self._hot.session_minutes(trade_date)

    def latest_complete_minute(self, trade_date: str) -> str | None:
        if self._hot is None:
            return None
        return self._hot.latest_complete_minute(trade_date)

    def latest_sector_minute(self, trade_date: str) -> str | None:
        if self._hot is None:
            return None
        return self._hot.latest_sector_minute(trade_date)

    def latest_stock_minute(self, trade_date: str) -> str | None:
        if self._hot is None:
            return None
        return self._hot.latest_stock_minute(trade_date)

    def latest_available_minute(self, trade_date: str) -> str | None:
        if self._hot is None:
            return None
        return self._hot.latest_available_minute(trade_date)

    def health(self) -> dict[str, object]:
        snapshot = self._meta.catalog_snapshot()
        gaps = 0
        latest_minute = None
        coverage = None
        batch_status = None
        if self._hot is not None:
            trade_dates = self.available_dates()
            if trade_dates:
                latest_date = trade_dates[-1]
                latest_minute = self._hot.latest_complete_minute(latest_date)
                with self._hot.connect(readonly=True) as connection:
                    row = connection.execute(
                        "SELECT coverage_pct, status FROM collection_status "
                        "WHERE trade_date=? ORDER BY minute DESC LIMIT 1",
                        (latest_date,),
                    ).fetchone()
                    if row:
                        coverage = float(row[0])
                        batch_status = str(row[1])
                    gaps = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM data_gap WHERE resolved=0"
                        ).fetchone()[0]
                    )
        heartbeat = self._read_heartbeat()
        return {
            "catalog_stale": snapshot.stale,
            "catalog_version": snapshot.catalog_version,
            "catalog_source": snapshot.source,
            "latest_complete_minute": latest_minute,
            "coverage_pct": coverage,
            "batch_status": batch_status,
            "unresolved_gaps": gaps,
            "collector_online": heartbeat.get("online", False),
            "collector_last_seen": heartbeat.get("last_seen"),
            "collector_roles": heartbeat.get("roles", {}),
        }

    def _read_heartbeat(self) -> dict[str, object]:
        from workbench.collector.heartbeat import read_collector_status

        return read_collector_status(self._data_dir)
