"""One-off query: sector intraday snapshots vs MAC official."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from easy_tdx import MacClient

SECTOR_ID = "881319"
SECTOR_NAME = "半导体"
COMPARE_MINUTES = ("09:30", "09:31", "10:48", "14:01", "14:02", "14:03", "14:26", "14:59")


def main() -> None:
    db = ROOT / "data" / "intraday.db"
    print(f"DB: {db} (exists={db.exists()})")
    if not db.exists():
        return

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    print("\n=== 库里所有板块采样概况 ===")
    for row in conn.execute(
        """
        SELECT trade_date, sector_id, COUNT(*) AS c,
               MIN(minute) AS first_min, MAX(minute) AS last_min
        FROM sector_intraday_snapshots
        GROUP BY trade_date, sector_id
        ORDER BY trade_date DESC, sector_id
        """
    ):
        print(dict(row))

    rows = conn.execute(
        """
        SELECT trade_date, minute, main_net, price, change_pct, sampled_at
        FROM sector_intraday_snapshots
        WHERE sector_id = ?
        ORDER BY trade_date DESC, minute
        """,
        (SECTOR_ID,),
    ).fetchall()

    print(f"\n=== {SECTOR_NAME} ({SECTOR_ID}) 全部入库记录: {len(rows)} 条 ===")
    if not rows:
        print("无半导体板块采样数据")
        conn.close()
        return

    trade_date = rows[0]["trade_date"]
    # If multiple dates, show latest date only detail
    day_rows = [r for r in rows if r["trade_date"] == trade_date]
    print(f"最新交易日: {trade_date}, 共 {len(day_rows)} 分钟")

    print("\n--- 关键分钟 (main_net 为入库时的累计主力，单位：元) ---")
    print(f"{'minute':<8} {'main_net(亿)':>14} {'sampled_at':<20} {'备注'}")
    for r in day_rows:
        m = r["minute"]
        if m in COMPARE_MINUTES or m == day_rows[0]["minute"] or m == day_rows[-1]["minute"]:
            yi = float(r["main_net"] or 0) / 1e8
            note = ""
            if m == "14:02":
                note = "← APP回放约 -304.38亿"
            print(f"{m:<8} {yi:>14.2f} {r['sampled_at']:<20} {note}")

    print("\n--- 全部分钟列表 ---")
    for r in day_rows:
        yi = float(r["main_net"] or 0) / 1e8
        print(f"  {r['minute']}  {yi:+.2f}亿  @ {r['sampled_at']}")

    conn.close()

    print("\n=== MAC 官方当日总额 (get_board_summary) ===")
    with MacClient.from_best_host() as client:
        summary = client.get_board_summary(SECTOR_ID)
        official = float(summary["main_net_amount"]) / 1e8
        print(f"main_net_amount = {official:.2f} 亿  (APP收盘约 -366.91亿)")

    last = day_rows[-1]
    db_close = float(last["main_net"] or 0) / 1e8
    print(f"\n=== 对比结论 ===")
    print(f"库中最后一笔 ({last['minute']}): {db_close:.2f} 亿")
    print(f"MAC 官方总额 NOW:              {official:.2f} 亿")
    print(f"差额:                          {db_close - official:+.2f} 亿")

    pt1402 = next((r for r in day_rows if r["minute"] == "14:02"), None)
    if pt1402:
        db1402 = float(pt1402["main_net"]) / 1e8
        print(f"\n14:02 库中: {db1402:.2f} 亿")
        print(f"14:02 APP: 约 -304.38 亿")
        print(f"14:02 momentum曲线: 约 -230.53 亿")


if __name__ == "__main__":
    main()
