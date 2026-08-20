from __future__ import annotations

import time
from typing import Any

from pytdx.hq import TdxHq_API

from .tdx_local import split_symbol

DEFAULT_HOSTS = [
    ("180.153.18.170", 7709),
    ("119.147.212.81", 7709),
    ("114.80.80.222", 7709),
    ("180.153.39.51", 7709),
    ("218.75.126.9", 7709),
    ("110.41.147.114", 7709),
    ("124.223.163.242", 7709),
]


class TdxClient:
    def __init__(self, hosts: list[tuple[str, int]] | None = None):
        self.hosts = hosts or DEFAULT_HOSTS
        self.api = TdxHq_API(multithread=True, raise_exception=False)
        self.host: tuple[str, int] | None = None

    def connect(self) -> None:
        if self.host:
            try:
                self.api.disconnect()
            except Exception:
                pass
            self.host = None
        for h, p in self.hosts:
            try:
                if self.api.connect(h, p, time_out=3):
                    self.host = (h, p)
                    return
            except Exception:
                continue
        raise RuntimeError("无法连接通达信行情服务器")

    def ensure(self) -> None:
        if not self.host:
            self.connect()

    def quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        self.ensure()
        pairs = []
        for s in symbols:
            try:
                pairs.append(split_symbol(s))
            except ValueError:
                continue
        out: list[dict[str, Any]] = []
        # pytdx max ~80 per request
        for i in range(0, len(pairs), 80):
            chunk = pairs[i : i + 80]
            rows = self.api.get_security_quotes(chunk) or []
            for row in rows:
                market = int(row.get("market", 0))
                code = str(row.get("code", ""))
                prefix = {0: "SZ", 1: "SH", 2: "BJ"}.get(market, "SZ")
                price = float(row.get("price") or 0)
                last = float(row.get("last_close") or 0)
                chg = ((price - last) / last * 100) if last else 0.0
                out.append(
                    {
                        "symbol": f"{prefix}{code}",
                        "code": code,
                        "market": market,
                        "price": price,
                        "last_close": last,
                        "open": float(row.get("open") or 0),
                        "high": float(row.get("high") or 0),
                        "low": float(row.get("low") or 0),
                        "amount": float(row.get("amount") or 0),
                        "volume": float(row.get("vol") or 0),
                        "change_pct": round(chg, 2),
                        "server_time": row.get("servertime"),
                    }
                )
        return out

    def minute_time(self, symbol: str) -> list[dict[str, Any]]:
        self.ensure()
        market, code = split_symbol(symbol)
        rows = self.api.get_minute_time_data(market, code) or []
        out = []
        for r in rows:
            out.append(
                {
                    "price": float(r.get("price") or 0),
                    "volume": float(r.get("vol") or 0),
                    "avg_price": float(r.get("avg_price") or 0),
                }
            )
        return out

    def transactions(self, symbol: str, count: int = 2000) -> list[dict[str, Any]]:
        self.ensure()
        market, code = split_symbol(symbol)
        # paginate backwards; pytdx returns up to 2000-ish
        rows = self.api.get_transaction_data(market, code, 0, min(count, 2000)) or []
        out = []
        for r in rows:
            out.append(
                {
                    "time": r.get("time") or r.get("hour_min"),
                    "price": float(r.get("price") or 0),
                    "volume": float(r.get("vol") or 0),
                    "buyorsell": int(r.get("buyorsell") if r.get("buyorsell") is not None else -1),
                }
            )
        return out

    def close(self) -> None:
        try:
            self.api.disconnect()
        except Exception:
            pass
        self.host = None
