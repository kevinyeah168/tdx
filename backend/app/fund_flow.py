from __future__ import annotations

from collections import defaultdict
from typing import Any

# Approximate Eastmoney-style amount buckets (CNY per trade).
# 主力 ≈ 超大单 + 大单。这是通达信分笔自研口径，不会与东财数字一致。
DEFAULT_THRESHOLDS = {
    "super": 1_000_000,  # >= 100万
    "large": 200_000,  # >= 20万
    "medium": 40_000,  # >= 4万
}

FLOW_KEYS = ("main", "super", "large", "medium", "small")


def _parse_hhmm(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        if n < 0:
            return None
        hh = n // 100
        mm = n % 100
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    s = str(value).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        if len(parts) >= 2:
            return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    if s.isdigit() and len(s) <= 4:
        n = int(s)
        return f"{n // 100:02d}:{n % 100:02d}"
    return None


def _bucket(amount: float, thresholds: dict[str, float]) -> str:
    if amount >= thresholds["super"]:
        return "super"
    if amount >= thresholds["large"]:
        return "large"
    if amount >= thresholds["medium"]:
        return "medium"
    return "small"


def _signed_amount(amount: float, buyorsell: int) -> float:
    """Return signed flow: buy +, sell -. Unknown side -> 0."""
    if buyorsell == 0:
        return amount
    if buyorsell == 1:
        return -amount
    return 0.0


def estimate_fund_flow_minutes(
    transactions: list[dict[str, Any]],
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build per-minute net inflow by order-size tier from TDX ticks."""
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    empty = {k: 0.0 for k in ("super", "large", "medium", "small")}
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: dict(empty))

    for t in transactions:
        minute = _parse_hhmm(t.get("time"))
        if not minute:
            continue
        price = float(t.get("price") or 0)
        vol = float(t.get("volume") or 0)
        if price <= 0 or vol <= 0:
            continue
        amount = price * vol * 100  # vol in lots
        side = int(t.get("buyorsell") if t.get("buyorsell") is not None else -1)
        signed = _signed_amount(amount, side)
        if signed == 0:
            continue
        buckets[minute][_bucket(amount, th)] += signed

    series: list[dict[str, Any]] = []
    cum = {k: 0.0 for k in FLOW_KEYS}
    for m in sorted(buckets.keys()):
        b = buckets[m]
        nets = {
            "super": b["super"],
            "large": b["large"],
            "medium": b["medium"],
            "small": b["small"],
            "main": b["super"] + b["large"],
        }
        row: dict[str, Any] = {"time": m}
        for k in FLOW_KEYS:
            cum[k] += nets[k]
            row[f"{k}_net"] = round(nets[k], 2)
            row[f"cum_{k}"] = round(cum[k], 2)
        row["net"] = row["main_net"]
        row["cum_net"] = row["cum_main"]
        series.append(row)
    return series


def synthetic_main_flow(main_net: float) -> list[dict[str, Any]]:
    """Linear fallback curve when tick shape is unavailable but official total exists."""
    from .trading_session import local_now

    now = local_now()
    hm_start = 9 * 60 + 30
    hm_end = min(now.hour * 60 + now.minute, 15 * 60)
    if hm_end < hm_start:
        hm_end = 15 * 60

    minutes: list[str] = []
    for hm in range(hm_start, hm_end + 1):
        if 11 * 60 + 30 <= hm < 13 * 60:
            continue
        hh, mm = divmod(hm, 60)
        minutes.append(f"{hh:02d}:{mm:02d}")
    if not minutes:
        minutes = ["09:30"]

    target = float(main_net or 0)
    flow: list[dict[str, Any]] = []
    n = len(minutes)
    for i, minute in enumerate(minutes):
        frac = (i + 1) / n
        cum_v = target * frac
        prev = target * (i / n)
        flow.append(
            {
                "time": minute,
                "main_net": round(cum_v - prev, 2),
                "cum_main": round(cum_v, 2),
                "cum_net": round(cum_v, 2),
                "net": round(cum_v - prev, 2),
            }
        )
    return flow


def calibrate_flow_to_main_net(
    flow_rows: list[dict[str, Any]],
    official_main_net: float,
) -> list[dict[str, Any]]:
    """Scale minute cumulative flow so the tail matches MAC official main net."""
    if not flow_rows:
        return []
    target = float(official_main_net or 0)
    if abs(target) < 1e-9:
        return flow_rows

    last_cum = float(flow_rows[-1].get("cum_main") or flow_rows[-1].get("cum_net") or 0)
    if abs(last_cum) < 1e-9:
        out: list[dict[str, Any]] = []
        n = len(flow_rows)
        for i, row in enumerate(flow_rows):
            frac = (i + 1) / n
            cum_v = target * frac
            prev = target * (i / n)
            out.append(
                {
                    **row,
                    "main_net": round(cum_v - prev, 2),
                    "cum_main": round(cum_v, 2),
                    "cum_net": round(cum_v, 2),
                    "net": round(cum_v - prev, 2),
                }
            )
        return out

    scale = target / last_cum
    out: list[dict[str, Any]] = []
    prev_cum = 0.0
    for row in flow_rows:
        cum_v = float(row.get("cum_main") or row.get("cum_net") or 0) * scale
        out.append(
            {
                **row,
                "main_net": round(cum_v - prev_cum, 2),
                "cum_main": round(cum_v, 2),
                "cum_net": round(cum_v, 2),
                "net": round(cum_v - prev_cum, 2),
            }
        )
        prev_cum = cum_v
    return out


def sum_sector_flow(stock_flows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum constituent minute nets by tier, then rebuild cumulative."""
    by_min: dict[str, dict[str, float]] = defaultdict(lambda: {k: 0.0 for k in FLOW_KEYS})
    for flow in stock_flows:
        for row in flow:
            m = row["time"]
            for k in FLOW_KEYS:
                by_min[m][k] += float(row.get(f"{k}_net") or 0)

    series: list[dict[str, Any]] = []
    cum = {k: 0.0 for k in FLOW_KEYS}
    for m in sorted(by_min.keys()):
        nets = by_min[m]
        row: dict[str, Any] = {"time": m}
        for k in FLOW_KEYS:
            cum[k] += nets[k]
            row[f"{k}_net"] = round(nets[k], 2)
            row[f"cum_{k}"] = round(cum[k], 2)
        row["net"] = row["main_net"]
        row["cum_net"] = row["cum_main"]
        series.append(row)
    return series
