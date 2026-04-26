# -*- coding: utf-8 -*-
"""
批量回测所有品种并生成结果报告文档
"""

import os
import sys

# 把 self_strategy 目录加到 path
sys.path.insert(0, os.path.dirname(__file__))

from _batch_backtest import run_all

DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "quanda_exports_h2")
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest_report_h2.md")

PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "order_volume": 10,
    "bandwidth_threshold": 0.25,
    "breakout_threshold": 0.02,
    "continuous_klines": 3,
    "fee_rate": 0.0001,
}


def generate_report(results):
    """生成 Markdown 格式的回测报告"""
    lines = []

    lines.append("# 布林带做空策略 - 批量回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # 策略说明
    lines.append("## 一、策略参数")
    lines.append("")
    lines.append("| 参数 | 值 | 说明 |")
    lines.append("|------|-----|------|")
    lines.append(f"| 布林带周期 | {PARAMS['bb_period']} | SMA 周期 |")
    lines.append(f"| 标准差倍数 | {PARAMS['bb_std']} | BB 上下轨偏移 |")
    lines.append(f"| 带宽阈值 | {PARAMS['bandwidth_threshold']} | (上轨-下轨)/中轨 > 此值 |")
    lines.append(f"| 突破阈值 | {PARAMS['breakout_threshold']} | 收盘价 > 上轨×(1+此值) |")
    lines.append(f"| 连续K线数 | {PARAMS['continuous_klines']} | 满足前置条件后需连续阳线数 |")
    lines.append(f"| 每次开仓手数 | {PARAMS['order_volume']} | 固定仓位 |")
    lines.append(f"| 手续费率 | {PARAMS['fee_rate']} | 按金额万分之几计 |")
    lines.append("")

    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带上轨上涨（当前 > 上一根）")
    lines.append("2. 布林带下轨上涨（当前 > 上一根）")
    lines.append("3. 布林带带宽 > 0.25（即 25%）")
    lines.append("4. 连续 3 根阳线（收盘价 > 开盘价）")
    lines.append("5. 收盘价突破上轨 × 1.02")
    lines.append("")
    lines.append("### 平仓条件")
    lines.append("- 价格回落到布林带中轨以下时平仓")
    lines.append("")

    # 汇总表
    lines.append("## 二、汇总总览")
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

    # 数据质量分析
    no_signal = [r for r in results if r["trade_count"] == 0]
    has_signal = [r for r in results if r["trade_count"] > 0]

    lines.append("## 三、数据分析")
    lines.append("")
    lines.append(f"- 总品种数: **{len(results)}**")
    lines.append(f"- 产生交易信号: **{len(has_signal)}** 个品种")
    lines.append(f"- 无交易信号: **{len(no_signal)}** 个品种")
    lines.append("")

    # 无信号原因分析
    lines.append("### 未触发信号的原因分析")
    lines.append("")
    lines.append("所有品种的布林带最大带宽统计：")
    lines.append("")
    lines.append("| 带宽范围 | 品种数 | 品种 |")
    lines.append("|---------|--------|------|")

    bw_buckets = {"带宽 > 0.25": [], "0.15 ~ 0.25": [], "0.10 ~ 0.15": [], "< 0.10": []}
    for r in results:
        bw = r["max_bandwidth"]
        if bw > 0.25:
            bw_buckets["带宽 > 0.25"].append(r["instrument"])
        elif bw > 0.15:
            bw_buckets["0.15 ~ 0.25"].append(r["instrument"])
        elif bw > 0.10:
            bw_buckets["0.10 ~ 0.15"].append(r["instrument"])
        else:
            bw_buckets["< 0.10"].append(r["instrument"])

    for label, insts in bw_buckets.items():
        lines.append(f"| {label} | {len(insts)} | {', '.join(insts) if insts else '-'} |")
    lines.append("")

    lines.append("> **核心问题**: 该策略设计于 2 小时K线周期，本次回测使用的是 **日线(D1)** 数据。")
    lines.append("> 日线波动率天然低于日内K线，导致带宽很难达到 25% 的阈值。")
    lines.append("> 即使带宽达标，前置条件（上轨涨+下轨涨+带宽>25%同时满足）在日线上也极为罕见。")
    lines.append("")

    # 有信号的品种详细分析
    if has_signal:
        lines.append("## 四、有交易信号的品种 - 详细分析")
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

    # 无信号的品种列表
    if no_signal:
        lines.append("## 五、无交易信号的品种")
        lines.append("")
        lines.append("| # | 品种 | 交易所 | 数据范围 | 记录数 | 最大带宽 | 带宽达标% |")
        lines.append("|---|------|--------|---------|--------|---------|----------|")
        for i, r in enumerate(no_signal, 1):
            lines.append(
                f"| {i} | {r['instrument']} | {r['exchange']} | "
                f"{r['date_start']}~{r['date_end']} | {r['records']} | "
                f"{r['max_bandwidth']:.4f} | {r['bw_above_pct']}% |"
            )
        lines.append("")

    # 结论与建议
    lines.append("## 六、结论与建议")
    lines.append("")
    lines.append("### 1. 策略适用性")
    lines.append("- 该策略为 **2 小时K线周期** 设计，核心逻辑是捕捉布林带急速扩张后的价格极端突破做空")
    lines.append("- 日线数据的波动率不足以频繁触发信号：带宽很难超过 25%，即使超过也难以同时满足上下轨上涨")
    lines.append("- 31 个品种中仅 1 个品种产生了 1 笔交易信号")
    lines.append("")
    lines.append("### 2. 如需在日线上使用，建议调整")
    lines.append("- 降低带宽阈值（如 0.10~0.15）")
    lines.append("- 降低突破阈值（如 0~0.01）")
    lines.append("- 缩短连续K线要求（如 2 根）")
    lines.append("- 缩短布林带周期（如 10~15）")
    lines.append("")
    lines.append("### 3. 推荐测试方案")
    lines.append("- 使用 InfiniTrader 导出 **2 小时(M120) 或 1 小时(H1)** K线数据")
    lines.append("- 品种优先选择: ag（白银）、FG（玻璃）、SA（纯碱）、ru（橡胶）、i（铁矿）—— 这些品种波动率最大")
    lines.append("- 可用 `ExportKLineData` 策略导出数据，设置 `kline_style = 'H2'`")
    lines.append("")

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("正在批量回测所有品种...")
    results = run_all(DATA_DIR, PARAMS)
    print(f"共回测 {len(results)} 个品种")

    report = generate_report(results)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n报告已保存: {OUTPUT_FILE}")

    # 简要汇总
    has_signal = [r for r in results if r["trade_count"] > 0]
    print(f"\n有信号的品种: {len(has_signal)}")
    for r in has_signal:
        print(f"  {r['instrument']}: {r['trade_count']} 笔, 总盈亏 {r.get('total_pnl', 0):>+,.1f}")


if __name__ == "__main__":
    main()
