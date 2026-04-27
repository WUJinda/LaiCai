# -*- coding: utf-8 -*-
"""
将 H2 数据合并为 H4 后运行批量回测（严谨 + 宽松两种模式）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _batch_backtest import run_all_with_modes, calc_trade_pnl

DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "quanda_exports_h2")
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest_report_h4.md")


def resample_h2_to_h4(records):
    """将 H2 K线数据每2根合并为1根 H4 K线"""
    h4 = []
    for i in range(0, len(records) - 1, 2):
        r1, r2 = records[i], records[i + 1]
        h4.append({
            "date": r2["date"],       # 取第二根的结束时间
            "open": r1["open"],
            "high": max(r1["high"], r2["high"]),
            "low": min(r1["low"], r2["low"]),
            "close": r2["close"],
            "volume": r1.get("volume", 0) + r2.get("volume", 0),
        })
    return h4


def load_and_resample(filepath):
    """加载 JSON 数据并重采样为 H4"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    records = raw.get("data", [])
    if len(records) < 4:
        return None, raw
    h4_records = resample_h2_to_h4(records)
    # 更新原始数据的 data 字段
    raw["data"] = h4_records
    raw["kline_style"] = "H4"
    return raw, None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("正在将 H2 数据合并为 H4 并批量回测...")

    # 加载所有品种，合并为 H4
    all_results = {}
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith("_kline.json"):
            continue
        filepath = os.path.join(DATA_DIR, fname)
        raw, _ = load_and_resample(filepath)
        if raw is None or len(raw.get("data", [])) < 25:
            continue

        # 写入临时 H4 JSON
        tmp_path = os.path.join(DATA_DIR, f"h4_{fname}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        all_results[fname] = tmp_path

    # 创建临时 H4 目录
    tmp_dir = os.path.join(DATA_DIR, "h4_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_files = []
    for fname, tmp_path in all_results.items():
        dest = os.path.join(tmp_dir, fname)
        os.rename(tmp_path, dest)
        tmp_files.append(dest)

    try:
        # 跑两种模式
        base_params = {
            "bb_period": 20,
            "bb_std": 2.0,
            "order_volume": 10,
            "bandwidth_threshold": 0.25,
            "breakout_threshold": 0.02,
            "fee_rate": 0.0001,
        }
        results = run_all_with_modes(tmp_dir, base_params)

        # 生成报告
        report = generate_report(results)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n报告已保存: {OUTPUT_FILE}")
    finally:
        # 清理临时文件
        for f in tmp_files:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)


def generate_report(results):
    """生成 Markdown 格式的回测报告"""
    from datetime import datetime
    import numpy as np
    lines = []

    lines.append("# 布林带做空策略 - H4 周期批量回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 数据来源: H2 数据合并为 H4（每 2 根 H2 合并为 1 根 H4）")
    lines.append("")

    lines.append("## 一、策略参数")
    lines.append("")
    lines.append("| 参数 | 严谨模式 | 宽松模式 | 说明 |")
    lines.append("|------|---------|---------|------|")
    lines.append("| 布林带周期 | 20 | 20 | SMA 周期 |")
    lines.append("| 标准差倍数 | 2.0 | 2.0 | BB 上下轨偏移 |")
    lines.append("| 带宽阈值 | 0.25 (25%) | 0.20 (20%) | (上轨-下轨)/中轨 > 此值 |")
    lines.append("| 突破阈值 | 0.02 (+2%) | 0.01 (+1%) | 收盘价 > 上轨×(1+此值) |")
    lines.append("| 趋势斜率窗口 | 3 | 3 | 最近3根K线斜率>0 |")
    lines.append("| 每次开仓手数 | 10 | 10 | 固定仓位 |")
    lines.append("| 手续费率 | 0.0001 | 0.0001 | 按金额万分之几计 |")
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
    for mode_key, mode_label in [("strict", "严谨模式（带宽≥25%，突破+2%）"), ("relaxed", "宽松模式（带宽≥20%，突破+1%）")]:
        mode_results = results.get(mode_key, [])
        lines.append(f"## 二、汇总总览 - {mode_label}")
        lines.append("")
        lines.append("| # | 品种 | 交易所 | 数据范围 | 记录数 | 最大带宽 | 带宽达标% | 交易笔数 | 总盈亏 | 胜率 |")
        lines.append("|---|------|--------|---------|--------|---------|----------|---------|--------|------|")

        for i, r in enumerate(mode_results, 1):
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
    strict_results = results.get("strict", [])
    relaxed_results = results.get("relaxed", [])

    lines.append("## 三、数据分析")
    lines.append("")
    strict_signal = [r for r in strict_results if r["trade_count"] > 0]
    relaxed_signal = [r for r in relaxed_results if r["trade_count"] > 0]
    lines.append(f"- 总品种数: **{len(strict_results)}**")
    lines.append(f"- 严谨模式有信号: **{len(strict_signal)}** 个品种")
    lines.append(f"- 宽松模式有信号: **{len(relaxed_signal)}** 个品种")
    lines.append("")

    # 带宽分布
    lines.append("### 带宽分布统计（H4 周期）")
    lines.append("")
    lines.append("| 带宽范围 | 品种数 | 品种 |")
    lines.append("|---------|--------|------|")
    bw_buckets = {"> 0.25": [], "0.20 ~ 0.25": [], "0.15 ~ 0.20": [], "< 0.15": []}
    for r in strict_results:
        bw = r["max_bandwidth"]
        if bw > 0.25:
            bw_buckets["> 0.25"].append(r["instrument"])
        elif bw > 0.20:
            bw_buckets["0.20 ~ 0.25"].append(r["instrument"])
        elif bw > 0.15:
            bw_buckets["0.15 ~ 0.20"].append(r["instrument"])
        else:
            bw_buckets["< 0.15"].append(r["instrument"])
    for label, insts in bw_buckets.items():
        lines.append(f"| {label} | {len(insts)} | {', '.join(insts) if insts else '-'} |")
    lines.append("")

    # 两种模式的有交易品种详情
    for mode_key, mode_label, mode_results_list in [
        ("strict", "严谨模式", strict_results),
        ("relaxed", "宽松模式", relaxed_results),
    ]:
        has_signal = [r for r in mode_results_list if r["trade_count"] > 0]
        if not has_signal:
            lines.append(f"## {mode_label} - 无交易信号")
            lines.append("")
            continue

        lines.append(f"## {mode_label} - 交易详情")
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
            if r.get("max_win"):
                lines.append(f"- 最大单笔盈利: {r['max_win']:>+,.1f} 元")
            if r.get("max_loss"):
                lines.append(f"- 最大单笔亏损: {r['max_loss']:>+,.1f} 元")
            if "max_drawdown" in r:
                lines.append(f"- 最大回撤: {r['max_drawdown']:>+,.1f} 元")
            if "avg_holding_days" in r:
                lines.append(f"- 平均持仓天数: {r['avg_holding_days']}")
            lines.append("")

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

    # H2 vs H4 对比总结
    lines.append("## 四、H2 vs H4 对比")
    lines.append("")
    lines.append("| 指标 | H2 周期 | H4 周期 |")
    lines.append("|------|---------|---------|")
    lines.append(f"| 严谨模式有信号品种数 | 0 | {len(strict_signal)} |")
    lines.append(f"| 宽松模式有信号品种数 | 1 (FG2505) | {len(relaxed_signal)} |")
    if relaxed_signal:
        relaxed_total = sum(r.get("total_pnl", 0) for r in relaxed_signal)
        lines.append(f"| 宽松模式总盈亏 | +12,145.8 | {relaxed_total:>+,.1f} |")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
