# -*- coding: utf-8 -*-
"""将 H2 数据合并为日线后运行批量回测（严谨 + 宽松）"""
import json
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _batch_backtest import run_all_with_modes

DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "quanda_exports_h2")
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest_report_d1.md")


def resample_h2_to_d1(records):
    """将 H2 K线数据按日期合并为日线"""
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["day"] = df["date"].dt.date

    daily = df.groupby("day").agg(
        date=("date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    return daily.to_dict("records")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("正在将 H2 数据合并为日线并批量回测...")

    tmp_dir = os.path.join(DATA_DIR, "d1_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        for fname in sorted(os.listdir(DATA_DIR)):
            if not fname.endswith("_kline.json"):
                continue
            filepath = os.path.join(DATA_DIR, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            records = raw.get("data", [])
            if len(records) < 25:
                continue

            d1_records = resample_h2_to_d1(records)
            raw["data"] = d1_records
            raw["kline_style"] = "D1"

            dest = os.path.join(tmp_dir, fname)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, default=str)

        base_params = {
            "bb_period": 20, "bb_std": 2.0, "order_volume": 10,
            "bandwidth_threshold": 0.25, "breakout_threshold": 0.02,
            "fee_rate": 0.0001,
        }
        results = run_all_with_modes(tmp_dir, base_params)

        # 生成报告
        strict_r = results.get("strict", [])
        relaxed_r = results.get("relaxed", [])
        strict_signal = [r for r in strict_r if r["trade_count"] > 0]
        relaxed_signal = [r for r in relaxed_r if r["trade_count"] > 0]

        lines = []
        lines.append("# 布林带做空策略 - 日线(D1)周期批量回测报告")
        lines.append("")
        lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> 数据来源: H2 数据合并为日线")
        lines.append("")

        lines.append("## 一、策略参数")
        lines.append("")
        lines.append("| 参数 | 严谨模式 | 宽松模式 | 说明 |")
        lines.append("|------|---------|---------|------|")
        lines.append("| 带宽阈值 | 0.25 (25%) | 0.20 (20%) | |")
        lines.append("| 突破阈值 | 0.02 (+2%) | 0.01 (+1%) | |")
        lines.append("| 趋势斜率窗口 | 3 | 3 | 最近3根K线斜率>0 |")
        lines.append("")

        for mode_key, mode_label, mode_results in [
            ("strict", "严谨模式（带宽≥25%，突破+2%）", strict_r),
            ("relaxed", "宽松模式（带宽≥20%，突破+1%）", relaxed_r),
        ]:
            lines.append(f"## 二、汇总 - {mode_label}")
            lines.append("")
            lines.append("| # | 品种 | 交易所 | 记录数 | 最大带宽 | 交易笔数 | 总盈亏 | 胜率 |")
            lines.append("|---|------|--------|--------|---------|---------|--------|------|")
            for i, r in enumerate(mode_results, 1):
                tc = r["trade_count"]
                tp = f"{r.get('total_pnl', '-'):>+,.1f}" if tc > 0 else "-"
                wr = f"{r.get('win_rate', '-')}%" if tc > 0 else "-"
                lines.append(f"| {i} | {r['instrument']} | {r['exchange']} | {r['records']} | {r['max_bandwidth']:.4f} | **{tc}** | {tp} | {wr} |")
            lines.append("")

        lines.append("## 三、对比总结")
        lines.append("")
        lines.append("| | H2 | H4 | D1 |")
        lines.append("|--|----|----|----|")
        lines.append(f"| 严谨模式信号数 | 0 | 0 | {len(strict_signal)} |")
        lines.append(f"| 宽松模式信号数 | 1 (FG) | 0 | {len(relaxed_signal)} |")
        lines.append("")

        # 宽松模式有信号就列详情
        if relaxed_signal:
            lines.append("## 四、交易详情（宽松模式）")
            lines.append("")
            for r in relaxed_signal:
                lines.append(f"### {r['instrument']}")
                lines.append(f"- 总盈亏: {r.get('total_pnl', 0):>+,.1f}")
                lines.append(f"- 交易笔数: {r['trade_count']}")
                if r["trades"]:
                    lines.append("")
                    lines.append("| # | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 净盈亏 |")
                    lines.append("|---|---------|--------|---------|--------|--------|")
                    for j, t in enumerate(r["trades"], 1):
                        od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                        cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])
                        lines.append(f"| {j} | {od} | {t['open_price']:,.0f} | {cd} | {t['close_price']:,.0f} | {t['net_pnl']:>+,.1f} |")
                    lines.append("")
        else:
            lines.append("## 四、交易详情")
            lines.append("")
            lines.append("无交易信号产生。")
            lines.append("")

        report = "\n".join(lines)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n报告已保存: {OUTPUT_FILE}")
    finally:
        for f in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, f))
        os.rmdir(tmp_dir)


if __name__ == "__main__":
    main()
