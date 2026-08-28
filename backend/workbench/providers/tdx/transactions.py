from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable

from workbench.domain import DataQuality, Transaction


ALGORITHM_VERSION = "tier-threshold-v1"
THRESHOLD_VERSION = "2026-08-20"
SUPER_THRESHOLD = 1_000_000.0
LARGE_THRESHOLD = 200_000.0
MEDIUM_THRESHOLD = 40_000.0
ESTIMATED_SOURCE = "tdx.transactions.estimated"


@dataclass(frozen=True, slots=True)
class TierThresholds:
    super_min: float = SUPER_THRESHOLD
    large_min: float = LARGE_THRESHOLD
    medium_min: float = MEDIUM_THRESHOLD
    version: str = THRESHOLD_VERSION


@dataclass(frozen=True, slots=True)
class TierTotals:
    super_delta: float = 0.0
    large_delta: float = 0.0
    medium_delta: float = 0.0
    small_delta: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "super": self.super_delta,
            "large": self.large_delta,
            "medium": self.medium_delta,
            "small": self.small_delta,
        }


def transaction_amount(price: float, volume: float) -> float:
    return float(price) * float(volume) * 100.0


def signed_amount(*, price: float, volume: float, side: str | int) -> float:
    amount = transaction_amount(price, volume)
    if side in {0, "buy", "B", "b"}:
        return amount
    if side in {1, "sell", "S", "s"}:
        return -amount
    return 0.0


def classify_tier(amount_abs: float, thresholds: TierThresholds | None = None) -> str:
    limits = thresholds or TierThresholds()
    if amount_abs >= limits.super_min:
        return "super"
    if amount_abs >= limits.large_min:
        return "large"
    if amount_abs >= limits.medium_min:
        return "medium"
    return "small"


def transaction_key(row: object) -> tuple[Any, ...]:
    if isinstance(row, dict):
        return (
            row.get("hour"),
            row.get("minute"),
            row.get("time"),
            row.get("price"),
            row.get("vol", row.get("volume")),
            row.get("buyorsell", row.get("side")),
            row.get("unknown_last"),
        )
    return (
        getattr(row, "hour", None),
        getattr(row, "minute", None),
        getattr(row, "time", None),
        getattr(row, "price", None),
        getattr(row, "vol", getattr(row, "volume", None)),
        getattr(row, "buyorsell", getattr(row, "side", None)),
        getattr(row, "unknown_last", None),
    )


def dedupe_transactions(rows: Iterable[object]) -> list[object]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[object] = []
    for row in rows:
        key = transaction_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _side_label(value: object) -> str:
    if value in {0, "buy", "B", "b"}:
        return "buy"
    if value in {1, "sell", "S", "s"}:
        return "sell"
    return "neutral"


def _row_time(row: object) -> time:
    if isinstance(row, dict):
        if "time" in row:
            parsed = str(row["time"])
            if len(parsed) >= 5:
                return datetime.strptime(parsed[:5], "%H:%M").time()
        hour = int(row.get("hour", 0))
        minute = int(row.get("minute", 0))
        return time(hour=hour, minute=minute)
    if hasattr(row, "hour") and hasattr(row, "minute"):
        return time(hour=int(row.hour), minute=int(row.minute))
    raise ValueError("transaction row is missing a time")


def normalize_transaction_row(row: object, *, symbol: str, trade_date: date) -> Transaction:
    if isinstance(row, dict):
        price = float(row["price"])
        volume = float(row.get("vol", row.get("volume", 0)))
        side = _side_label(row.get("buyorsell", row.get("side", "neutral")))
    else:
        price = float(row.price)
        volume = float(getattr(row, "vol", getattr(row, "volume", 0)))
        side = _side_label(getattr(row, "buyorsell", getattr(row, "side", "neutral")))
    timestamp = datetime.combine(trade_date, _row_time(row))
    amount = abs(transaction_amount(price, volume))
    return Transaction(
        symbol=symbol,
        trade_date=trade_date,
        timestamp=timestamp,
        price=price,
        volume=volume,
        amount=amount,
        side=side,
    )


def aggregate_tier_deltas(
    rows: Iterable[object],
    *,
    thresholds: TierThresholds | None = None,
) -> TierTotals:
    totals = TierTotals()
    for row in rows:
        if isinstance(row, dict):
            price = float(row["price"])
            volume = float(row.get("vol", row.get("volume", 0)))
            side = row.get("buyorsell", row.get("side", "neutral"))
        else:
            price = float(row.price)
            volume = float(getattr(row, "vol", getattr(row, "volume", 0)))
            side = getattr(row, "buyorsell", getattr(row, "side", "neutral"))
        signed = signed_amount(price=price, volume=volume, side=side)
        if signed == 0.0:
            continue
        tier = classify_tier(abs(signed), thresholds)
        if tier == "super":
            totals = TierTotals(
                super_delta=totals.super_delta + signed,
                large_delta=totals.large_delta,
                medium_delta=totals.medium_delta,
                small_delta=totals.small_delta,
            )
        elif tier == "large":
            totals = TierTotals(
                super_delta=totals.super_delta,
                large_delta=totals.large_delta + signed,
                medium_delta=totals.medium_delta,
                small_delta=totals.small_delta,
            )
        elif tier == "medium":
            totals = TierTotals(
                super_delta=totals.super_delta,
                large_delta=totals.large_delta,
                medium_delta=totals.medium_delta + signed,
                small_delta=totals.small_delta,
            )
        else:
            totals = TierTotals(
                super_delta=totals.super_delta,
                large_delta=totals.large_delta,
                medium_delta=totals.medium_delta,
                small_delta=totals.small_delta + signed,
            )
    return totals


def estimated_quality() -> DataQuality:
    return DataQuality.ESTIMATED
