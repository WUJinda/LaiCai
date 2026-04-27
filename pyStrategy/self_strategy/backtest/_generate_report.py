# -*- coding: utf-8 -*-
"""
批量回测所有品种并生成结果报告文档
"""

import os
import sys

# 把 self_strategy 目录加到 path
sys.path.insert(0, os.path.dirname(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from _batch_backtest import run_all, run_all_with_modes, calc_bbands, get_multiplier

# matplotlib 中文支持
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "quanda_exports_h2")
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest_report_h2.md")

BASE_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "order_volume": 10,
    "fee_rate": 0.0001,
}

MODE_LABELS = {
    "strict": "严谨模式（带宽≥25%，突破+2%）",
    "relaxed": "宽松模式（带宽≥20%，突破+1%）",
}


def plot_instrument_charts(data_dir, all_results):
    """为有交易的品种生成过程图"""
    import json

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for mode, results in all_results.items():
        for r in results:
            if r["trade_count"] == 0:
                continue

            # 查找对应的数据文件
            fname = r["instrument"] + "_kline.json"
            filepath = os.path.join(data_dir, fname)
            if not os.path.exists(filepath):
                continue

            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)

            records = raw.get("data", [])
            if len(records) < BASE_PARAMS["bb_period"] + 5:
                continue

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            upper, middle, lower, bandwidth = calc_bbands(
                df["close"].values, BASE_PARAMS["bb_period"], BASE_PARAMS["bb_std"]
            )
            df["bb_upper"] = upper
            df["bb_middle"] = middle
            df["bb_lower"] = lower

            trades = r["trades"]
            close_vals = df["close"].values

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                            gridspec_kw={"height_ratios": [3, 1]})

            dates = df["date"]
            ax1.plot(dates, close_vals, color="black", linewidth=0.8, label="收盘价")
            ax1.plot(dates, df["bb_upper"], "r--", linewidth=0.6, alpha=0.7, label="上轨")
            ax1.plot(dates, df["bb_middle"], "b--", linewidth=0.6, alpha=0.7, label="中轨")
            ax1.plot(dates, df["bb_lower"], "g--", linewidth=0.6, alpha=0.7, label="下轨")

            for t in trades:
                od = t["open_date"]
                cd = t["close_date"]
                ax1.scatter(od, t["open_price"], marker="v", color="red",
                            s=120, zorder=5, edgecolors="darkred")
                ax1.scatter(cd, t["close_price"], marker="^", color="limegreen",
                            s=120, zorder=5, edgecolors="darkgreen")

            ax1.scatter([], [], marker="v", color="red", s=100, label="开空仓")
            ax1.scatter([], [], marker="^", color="limegreen", s=100, label="平空仓")
            ax1.set_title(f"布林带做空策略回测 - {r['instrument']}（{MODE_LABELS[mode]}）",
                          fontsize=14, fontweight="bold")
            ax1.set_ylabel("价格")
            ax1.legend(loc="upper left", fontsize=9)
            ax1.grid(True, alpha=0.3)

            # 累计收益
            pnls = [t["net_pnl"] for t in trades]
            cumulative = np.cumsum(pnls)
            trade_dates = [t["close_date"] for t in trades]
            ax2.plot(trade_dates, cumulative, color="royalblue", linewidth=1.2)
            ax2.fill_between(trade_dates, cumulative, 0,
                             where=cumulative >= 0, alpha=0.3, color="green")
            ax2.fill_between(trade_dates, cumulative, 0,
                             where=cumulative < 0, alpha=0.3, color="red")
            ax2.axhline(y=0, color="gray", linewidth=0.5)
            ax2.set_title("累计收益", fontsize=12)
            ax2.set_ylabel("盈亏金额")
            ax2.set_xlabel("日期")
            ax2.grid(True, alpha=0.3)

            plt.tight_layout()
            chart_path = os.path.join(OUTPUT_DIR,
                                      f"backtest_{mode}_{r['instrument']}.png")
            fig.savefig(chart_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            print(f"  图表已保存: {chart_path}")


def generate_report(all_results):
    """生成 Markdown 格式的回测报告"""
    lines = []

    lines.append("# 布林带做空策略 - 批量回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 策略说明
    lines.append("## 一、策略参数")
    lines.append("")
    lines.append("| 参数 | 严谨模式 | 宽松模式 | 说明 |")
    lines.append("|------|---------|---------|------|")
    lines.append(f"| 布林带周期 | {BASE_PARAMS['bb_period']} | {BASE_PARAMS['bb_period']} | SMA 周期 |")
    lines.append(f"| 标准差倍数 | {BASE_PARAMS['bb_std']} | {BASE_PARAMS['bb_std']} | BB 上下轨偏移 |")
    lines.append(f"| 带宽阈值 | 0.25 (25%) | 0.20 (20%) | (上轨-下轨)/中轨 > 此值 |")
    lines.append(f"| 突破阈值 | 0.02 (+2%) | 0.01 (+1%) | 收盘价 > 上轨×(1+此值) |")
    lines.append(f"| 趋势斜率窗口 | 3 | 3 | 最近3根K线斜率>0 |")
    lines.append(f"| 每次开仓手数 | {BASE_PARAMS['order_volume']} | {BASE_PARAMS['order_volume']} | 固定仓位 |")
    lines.append(f"| 手续费率 | {BASE_PARAMS['fee_rate']} | {BASE_PARAMS['fee_rate']} | 按金额万分之几计 |")
    lines.append("")

    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带趋势确认：最近3根K线，上轨和下轨斜率同时 > 0")
    lines.append("2. 布林带带宽 > 阈值（严谨25%，宽松20%）")
    lines.append("3. 收盘价突破上轨 × (1+突破阈值)（严谨+2%，宽松+1%）")
    lines.append("")
    lines.append("### 平仓条件")
    lines.append("- 价格回落到布林带中轨以下时平仓")
    lines.append("")

    # 两种模式的汇总表
    for mode in ["strict", "relaxed"]:
        results = all_results[mode]
        lines.append(f"## 二、汇总总览 - {MODE_LABELS[mode]}")
        lines.append("")
        lines.append("| # | 品种 | 交易所 | 数据范围 | 记录数 | 最大带宽 | 带宽达标% | 交易笔数 | 总盈亏 | 胜率 |")
        lines.append("|---|------|--------|---------|--------|---------|----------|---------|--------|------|")

        for i, r in enumerate(results, 1):
            tc = r["trade_count"]
            total_pnl = f"{r.get('total_pnl', '-'):>+,.1f}" if tc > 0 else "-"
            win_rate = f"{r.get('win_rate', '-')}%" if tc > 0 else "-"
            lines.append(
                f"| {i} | {r['instrument']} | {r['exchange']} | "
                f"{r['date_start']}~{r['date_end']} | {r['records']} | "
                f"{r['max_bandwidth']:.4f} | {r['bw_above_pct']}% | "
                f"**{tc}** | {total_pnl} | {win_rate} |"
            )

        lines.append("")

    # 数据分析
    all_instruments = set()
    for mode_results in all_results.values():
        for r in mode_results:
            all_instruments.add(r["instrument"])

    strict_has = [r for r in all_results["strict"] if r["trade_count"] > 0]
    relaxed_has = [r for r in all_results["relaxed"] if r["trade_count"] > 0]

    lines.append("## 三、数据分析")
    lines.append("")
    lines.append(f"- 总品种数: **{len(all_instruments)}**")
    lines.append(f"- 严谨模式有信号: **{len(strict_has)}** 个品种")
    lines.append(f"- 宽松模式有信号: **{len(relaxed_has)}** 个品种")
    lines.append("")

    # 无信号原因分析
    lines.append("### 未触发信号的原因分析")
    lines.append("")
    lines.append("所有品种的布林带最大带宽统计：")
    lines.append("")
    lines.append("| 带宽范围 | 品种数 | 品种 |")
    lines.append("|---------|--------|------|")

    bw_buckets = {"带宽 > 0.25": [], "0.20 ~ 0.25": [], "0.15 ~ 0.20": [], "< 0.15": []}
    for r in all_results["strict"]:
        bw = r["max_bandwidth"]
        if bw > 0.25:
            bw_buckets["带宽 > 0.25"].append(r["instrument"])
        elif bw > 0.20:
            bw_buckets["0.20 ~ 0.25"].append(r["instrument"])
        elif bw > 0.15:
            bw_buckets["0.15 ~ 0.20"].append(r["instrument"])
        else:
            bw_buckets["< 0.15"].append(r["instrument"])

    for label, insts in bw_buckets.items():
        lines.append(f"| {label} | {len(insts)} | {', '.join(insts) if insts else '-'} |")
    lines.append("")

    # 有信号的品种详细分析
    for mode in ["strict", "relaxed"]:
        results = all_results[mode]
        has_signal = [r for r in results if r["trade_count"] > 0]
        if not has_signal:
            continue

        lines.append(f"## 四、有交易信号的品种 - {MODE_LABELS[mode]}")
        lines.append("")

        for r in has_signal:
            lines.append(f"### {r['instrument']}（{r['exchange']}）")
            lines.append("")
            lines.append(f"- 数据范围: {r['date_start']} ~ {r['date_end']}（{r['records']} 条记录）")
            lines.append(f"- 合约乘数: {r['volume_multiple']}")
            lines.append(f"- 最大带宽: {r['max_bandwidth']:.4f}")
            lines.append(f"- 交易笔数: {r['trade_count']}")
            lines.append(f"- 盈利/亏损: {r.get('win_count', 0)}/{r.get('loss_count', 0)}")
            lines.append(f"- 胜率: {r.get('win_rate', '-')}%")
            lines.append(f"- 总盈亏: {r.get('total_pnl', 0):>+,.1f} 元")
            lines.append(f"- 最大单笔盈利: {r.get('max_win', 0):>+,.1f} 元")
            lines.append(f"- 最大单笔亏损: {r.get('max_loss', 0):>+,.1f} 元")
            if "max_drawdown" in r:
                lines.append(f"- 最大回撤: {r['max_drawdown']:>+,.1f} 元")
            lines.append(f"- 平均持仓天数: {r.get('avg_holding_days', '-')} 天")
            lines.append("")

            # 交易明细表
            if r["trades"]:
                lines.append("交易明细:")
                lines.append("")
                lines.append("| # | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | 持仓天数 | 点数盈亏 | 手续费 | 净盈亏 |")
                lines.append("|---|---------|--------|---------|--------|------|---------|---------|--------|--------|")
                for j, t in enumerate(r["trades"], 1):
                    od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                    cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])
                    lines.append(
                        f"| {j} | {od} | {t['open_price']:,.0f} | {cd} | {t['close_price']:,.0f} | "
                        f"{t['volume']} | {t['holding_days']} | {t['points']:>+,.1f} | "
                        f"{t['fee']:,.1f} | {t['net_pnl']:>+,.1f} |"
                    )
                lines.append("")

            # 图表引用
            chart_file = f"backtest_{mode}_{r['instrument']}.png"
            lines.append(f"![{r['instrument']}回测图]({chart_file})")
            lines.append("")

    # 结论与建议
    lines.append("## 五、结论与建议")
    lines.append("")
    lines.append("### 1. 策略逻辑更新")
    lines.append("- 采用**斜率趋势确认**替代原有的单根比较（上轨>上一根 + 下轨>上一根）")
    lines.append("- 使用最近3根K线的上下轨斜率同时>0作为趋势过滤，减少噪音信号")
    lines.append("- 移除了连续阳线计数逻辑，简化了开仓条件")
    lines.append("")
    lines.append("### 2. 两种模式对比")
    lines.append(f"- 严谨模式（带宽25%+突破2%）：{len(strict_has)} 个品种产生信号")
    lines.append(f"- 宽松模式（带宽20%+突破1%）：{len(relaxed_has)} 个品种产生信号")
    if len(strict_has) == 0 and len(relaxed_has) == 0:
        lines.append("- 两种模式均未触发信号，可能需要进一步降低阈值或使用更短周期的K线数据")
    lines.append("")
    lines.append("### 3. 数据周期影响")
    lines.append("- 该策略为 **2 小时K线周期** 设计，本次回测使用的是 **日线(D1)** 数据")
    lines.append("- 日线波动率天然低于日内K线，导致带宽很难达到阈值")
    lines.append("")
    lines.append("### 4. 推荐测试方案")
    lines.append("- 使用 InfiniTrader 导出 **2 小时(M120) 或 1 小时(H1)** K线数据")
    lines.append("- 品种优先选择: ag（白银）、FG（玻璃）、SA（纯碱）、ru（橡胶）、i（铁矿）")
    lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("正在批量回测所有品种（两种模式）...")
    all_results = run_all_with_modes(DATA_DIR, BASE_PARAMS)

    for mode in all_results:
        print(f"  {MODE_LABELS[mode]}: {len(all_results[mode])} 个品种")
        has_signal = [r for r in all_results[mode] if r["trade_count"] > 0]
        for r in has_signal:
            print(f"    {r['instrument']}: {r['trade_count']} 笔, 总盈亏 {r.get('total_pnl', 0):>+,.1f}")

    # 生成过程图
    print("\n生成过程图...")
    plot_instrument_charts(DATA_DIR, all_results)

    # 生成报告
    report = generate_report(all_results)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
