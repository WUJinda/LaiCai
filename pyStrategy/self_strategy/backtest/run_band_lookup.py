# -*- coding: utf-8 -*-
"""
查表法带宽阈值回测：各品种使用自身P75作为bandwidth_threshold
"""
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _batch_backtest import run_all, calc_bbands, BANDWIDTH_THRESHOLDS

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
DATA_DIRS = {
    "H2": os.path.join(DESKTOP, "quanda_exports_h2"),
    "H4": os.path.join(DESKTOP, "quanda_exports_h4"),
    "D1": os.path.join(DESKTOP, "quanda_exports_d1"),
}
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res_band"))


def run_all_periods(breakout_threshold=0.01):
    """用查表法阈值跑所有周期，返回 {period: results}"""
    base_params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "bandwidth_threshold": 0.04,  # 会被查表覆盖，这里只是兜底
        "breakout_threshold": breakout_threshold,
        "fee_rate": 0.0001,
    }

    all_results = {}
    for period_name in ["H2", "H4", "D1"]:
        data_dir = DATA_DIRS[period_name]
        if not os.path.isdir(data_dir):
            print(f"  跳过 {period_name}（目录不存在）")
            continue
        print(f"  回测 {period_name} ...", flush=True)
        results = run_all(data_dir, base_params)
        trade_count = sum(r["trade_count"] for r in results)
        print(f"    {period_name}: {len(results)} 个品种, {trade_count} 笔交易")
        all_results[period_name] = results

    return all_results


def build_report(all_results, breakout_threshold):
    """生成查表法回测报告"""
    lines = []
    lines.append("# 查表法带宽阈值回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 阈值来源: 各品种布林带带宽 P75（来自 bandwidth_stats.json）")
    lines.append(f"> 突破阈值: {breakout_threshold}")
    lines.append("")

    # 参数表
    lines.append("## 一、各品种带宽阈值")
    lines.append("")
    lines.append("| 品种 | 阈值(P75) | 说明 |")
    lines.append("|------|----------|------|")
    for symbol, threshold in sorted(BANDWIDTH_THRESHOLDS.items()):
        lines.append(f"| {symbol} | {threshold:.6f} | 布林带BB(20,2) bandwidth P75 |")
    lines.append("")

    # 开平仓条件
    lines.append("## 二、策略条件")
    lines.append("")
    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带趋势确认：最近3根K线，上轨和下轨斜率同时 > 0")
    lines.append("2. 布林带带宽 > 该品种P75阈值（查表）")
    lines.append(f"3. 收盘价突破上轨 × (1+{breakout_threshold})")
    lines.append("")
    lines.append("### 平仓条件")
    lines.append("- 价格回落到布林带中轨以下")
    lines.append("")

    # 资金管理
    lines.append("### 资金管理")
    lines.append("- 总敞口: 1000万, 单笔保证金 ≤ 100万, 同时持仓保证金 ≤ 600万")
    lines.append("")

    # 汇总
    period_labels = {"H2": "2小时", "H4": "4小时", "D1": "日线"}

    lines.append("## 三、各周期汇总")
    lines.append("")
    lines.append("| 周期 | 有交易品种数 | 总交易笔数 | 总盈亏 | 总保证金 | 总收益率 |")
    lines.append("|------|------------|-----------|--------|---------|---------|")
    for period_name, results in all_results.items():
        traded = [r for r in results if r["trade_count"] > 0]
        total_trades = sum(r["trade_count"] for r in traded)
        total_pnl = sum(r.get("total_pnl", 0) for r in traded)
        total_margin = sum(r.get("total_margin", 0) for r in traded)
        roi = f"{total_pnl/total_margin*100:+.2f}%" if total_margin > 0 else "-"
        lines.append(f"| {period_labels[period_name]} | {len(traded)} | {total_trades} | {total_pnl:>+,.0f} | {total_margin:>+,.0f} | {roi} |")
    lines.append("")

    # 各品种详情
    lines.append("## 四、各品种详情")
    lines.append("")

    for period_name, results in all_results.items():
        traded = [r for r in results if r["trade_count"] > 0]
        if not traded:
            lines.append(f"### {period_labels[period_name]}：无交易")
            lines.append("")
            continue

        lines.append(f"### {period_labels[period_name]}")
        lines.append("")
        lines.append("| 品种 | 交易笔数 | 胜率 | 总盈亏 | 总保证金 | 收益率 | 最大回撤 | 均持仓天数 |")
        lines.append("|------|---------|------|--------|---------|--------|---------|-----------|")
        for r in sorted(traded, key=lambda x: x.get("total_pnl", 0), reverse=True):
            wr = f"{r['win_rate']}%" if "win_rate" in r else "-"
            pnl = f"{r['total_pnl']:>+,.0f}" if "total_pnl" in r else "-"
            mg = f"{r['total_margin']:>+,.0f}" if "total_margin" in r else "-"
            rr = f"{r['avg_return_rate']:+.2f}%" if "avg_return_rate" in r else "-"
            dd = f"{r['max_drawdown']:>+,.0f}" if "max_drawdown" in r else "-"
            hd = f"{r['avg_holding_days']}" if "avg_holding_days" in r else "-"
            lines.append(f"| {r['instrument']} | {r['trade_count']} | {wr} | {pnl} | {mg} | {rr} | {dd} | {hd} |")
        lines.append("")

    # 交易明细
    lines.append("## 五、交易明细")
    lines.append("")

    for period_name, results in all_results.items():
        for r in results:
            if r["trade_count"] == 0 or not r.get("trades"):
                continue
            lines.append(f"### {r['instrument']} ({period_labels[period_name]})")
            lines.append(f"- 数据: {r['date_start']} ~ {r['date_end']} ({r['records']}条)")
            lines.append(f"- 合约乘数: {r['volume_multiple']}, 保证金率: {r['margin_rate']*100:.0f}%")
            lines.append("")
            lines.append("| # | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | 持仓天 | 保证金 | 净盈亏 | 收益率 |")
            lines.append("|---|---------|--------|---------|--------|------|--------|--------|--------|--------|")
            for j, t in enumerate(r["trades"], 1):
                od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])
                lines.append(
                    f"| {j} | {od} | {t['open_price']:,.0f} | {cd} | {t['close_price']:,.0f} | "
                    f"{t['volume']} | {t['holding_days']} | {t['margin']:>+,.0f} | "
                    f"{t['net_pnl']:>+,.0f} | {t['return_rate']:>+,.1f}% |"
                )
            lines.append("")

    # 结论
    lines.append("## 六、结论")
    lines.append("")
    total_all_trades = 0
    total_all_pnl = 0
    total_all_margin = 0
    total_all_wins = 0
    for period_name, results in all_results.items():
        for r in results:
            if r["trade_count"] > 0:
                total_all_trades += r["trade_count"]
                total_all_pnl += r.get("total_pnl", 0)
                total_all_margin += r.get("total_margin", 0)
                total_all_wins += r.get("win_count", 0)

    lines.append(f"- 总交易笔数: {total_all_trades}")
    lines.append(f"- 总盈亏: {total_all_pnl:>+,.0f} 元")
    lines.append(f"- 总保证金: {total_all_margin:>+,.0f} 元")
    if total_all_margin > 0:
        lines.append(f"- 总收益率: {total_all_pnl/total_all_margin*100:+.2f}%")
    if total_all_trades > 0:
        lines.append(f"- 整体胜率: {total_all_wins}/{total_all_trades} = {total_all_wins/total_all_trades*100:.1f}%")
    lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    breakout_threshold = 0.01

    print("=" * 50)
    print("查表法带宽阈值回测")
    print(f"各品种使用自身P75作为 bandwidth_threshold")
    print(f"突破阈值: {breakout_threshold}")
    print("=" * 50)

    all_results = run_all_periods(breakout_threshold)

    # 生成报告
    print("\n生成报告...")
    report = build_report(all_results, breakout_threshold)

    report_path = os.path.join(OUTPUT_DIR, "backtest_band_lookup.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"报告已保存: {report_path}")

    # 同时保存JSON原始数据
    json_path = os.path.join(OUTPUT_DIR, "backtest_band_lookup.json")
    # 把日期转成字符串以便JSON序列化
    json_data = {}
    for period_name, results in all_results.items():
        period_data = []
        for r in results:
            rd = dict(r)
            if "trades" in rd:
                for t in rd["trades"]:
                    if hasattr(t["open_date"], "strftime"):
                        t["open_date"] = t["open_date"].strftime("%Y-%m-%d %H:%M")
                    if hasattr(t["close_date"], "strftime"):
                        t["close_date"] = t["close_date"].strftime("%Y-%m-%d %H:%M")
            period_data.append(rd)
        json_data[period_name] = period_data

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"JSON数据已保存: {json_path}")

    # 打印摘要
    print("\n" + "=" * 50)
    print("回测摘要")
    print("=" * 50)
    for period_name, results in all_results.items():
        traded = [r for r in results if r["trade_count"] > 0]
        total_pnl = sum(r.get("total_pnl", 0) for r in traded)
        total_trades = sum(r["trade_count"] for r in traded)
        print(f"  {period_name}: {len(traded)}个品种有交易, {total_trades}笔, 盈亏 {total_pnl:>+,.0f}")
    print("完成！")


if __name__ == "__main__":
    main()
