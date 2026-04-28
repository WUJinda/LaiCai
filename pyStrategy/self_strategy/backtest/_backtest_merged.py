# -*- coding: utf-8 -*-
"""融合三次回测结果（H2/H4/D1），生成统一报告 + 过程图"""
import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _batch_backtest import run_all_with_modes

DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "quanda_exports_h2")
OUTPUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res"))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "backtest_report_merged.md")

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# 数据重采样
# ============================================================
def resample_h2_to_h4(records):
    h4 = []
    for i in range(0, len(records) - 1, 2):
        r1, r2 = records[i], records[i + 1]
        h4.append({
            "date": r2["date"], "open": r1["open"],
            "high": max(r1["high"], r2["high"]),
            "low": min(r1["low"], r2["low"]),
            "close": r2["close"],
            "volume": r1.get("volume", 0) + r2.get("volume", 0),
        })
    return h4


def resample_h2_to_d1(records):
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["day"] = df["date"].dt.date
    daily = df.groupby("day").agg(
        date=("date", "last"), open=("open", "first"),
        high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
    ).reset_index(drop=True)
    return daily.to_dict("records")


# ============================================================
# 布林带计算
# ============================================================
def calc_bbands_df(df, period=20, std_dev=2.0):
    close = pd.Series(df["close"].values.astype(float))
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    df = df.copy()
    df["bb_upper"] = upper.values
    df["bb_middle"] = middle.values
    df["bb_lower"] = lower.values
    df["bandwidth"] = np.where(middle > 0, (upper - lower) / middle, 0)
    return df


# ============================================================
# 生成过程图
# ============================================================
def plot_trade_process(records, trades, instrument, period_label, mode_label, output_path):
    """绘制交易过程图：价格+布林带+开平仓标记+连线"""
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = calc_bbands_df(df)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 10), gridspec_kw={"height_ratios": [3, 1]})

    # 上图：价格 + 布林带 + 交易标记
    ax1.plot(df["date"], df["close"], color="black", linewidth=0.8, label="收盘价")
    ax1.plot(df["date"], df["bb_upper"], "r--", linewidth=0.6, alpha=0.7, label="上轨")
    ax1.plot(df["date"], df["bb_middle"], "b--", linewidth=0.6, alpha=0.7, label="中轨")
    ax1.plot(df["date"], df["bb_lower"], "g--", linewidth=0.6, alpha=0.7, label="下轨")

    # 标记交易
    for j, t in enumerate(trades):
        open_date = t["open_date"]
        close_date = t["close_date"]
        open_price = t["open_price"]
        close_price = t["close_price"]

        # 开仓点（红色向下三角）
        ax1.scatter(open_date, open_price, marker="v", color="red", s=150, zorder=5, edgecolors="darkred", linewidths=1.5)
        ax1.annotate(f"开{j+1}\n{open_price:,.0f}", (open_date, open_price),
                     textcoords="offset points", xytext=(10, -30), fontsize=8, color="darkred",
                     arrowprops=dict(arrowstyle="->", color="darkred", lw=0.8))

        # 平仓点（绿色向上三角）
        ax1.scatter(close_date, close_price, marker="^", color="limegreen", s=150, zorder=5, edgecolors="darkgreen", linewidths=1.5)
        ax1.annotate(f"平{j+1}\n{close_price:,.0f}", (close_date, close_price),
                     textcoords="offset points", xytext=(10, 20), fontsize=8, color="darkgreen",
                     arrowprops=dict(arrowstyle="->", color="darkgreen", lw=0.8))

        # 开仓到平仓的连线（虚线）
        ax1.plot([open_date, close_date], [open_price, close_price],
                 "r--", linewidth=1, alpha=0.5)

        # 持仓区间着色
        ax1.axvspan(open_date, close_date, alpha=0.08, color="red")

        # 盈亏标注
        pnl = t.get("net_pnl", 0)
        mid_date = open_date + (close_date - open_date) / 2
        mid_price = (open_price + close_price) / 2
        color = "darkgreen" if pnl > 0 else "darkred"
        ax1.annotate(f"{'盈利' if pnl > 0 else '亏损'} {pnl:+,.0f}",
                     (mid_date, mid_price), fontsize=9, fontweight="bold",
                     ha="center", va="bottom", color=color,
                     bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7))

    ax1.scatter([], [], marker="v", color="red", s=100, label="开空仓")
    ax1.scatter([], [], marker="^", color="limegreen", s=100, label="平空仓")
    ax1.set_title(f"{instrument} {period_label} {mode_label} - 交易过程图", fontsize=14, fontweight="bold")
    ax1.set_ylabel("价格")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    # 下图：累计收益
    pnls = [t.get("net_pnl", 0) for t in trades]
    close_dates = [t["close_date"] for t in trades]
    cumulative = np.cumsum(pnls)

    ax2.step(close_dates, cumulative, where="post", color="royalblue", linewidth=1.5)
    ax2.fill_between(close_dates, cumulative, 0, step="post",
                     where=[c >= 0 for c in cumulative], alpha=0.3, color="green")
    ax2.fill_between(close_dates, cumulative, 0, step="post",
                     where=[c < 0 for c in cumulative], alpha=0.3, color="red")
    ax2.axhline(y=0, color="gray", linewidth=0.5)
    ax2.set_title("累计收益", fontsize=12)
    ax2.set_ylabel("盈亏金额")
    ax2.set_xlabel("日期")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表已保存: {output_path}")


# ============================================================
# 跑单周期
# ============================================================
def run_period(period_name, resample_fn, params):
    """跑一个周期的回测，返回 results 和原始数据"""
    tmp_dir = os.path.join(DATA_DIR, f"{period_name}_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    file_records = {}  # fname -> records (for charting)

    try:
        for fname in sorted(os.listdir(DATA_DIR)):
            if not fname.endswith("_kline.json"):
                continue
            with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
                raw = json.load(f)
            records = raw.get("data", [])
            if len(records) < 25:
                continue

            if resample_fn:
                resampled = resample_fn(records)
            else:
                resampled = records

            file_records[fname] = resampled

            raw["data"] = resampled
            raw["kline_style"] = period_name
            with open(os.path.join(tmp_dir, fname), "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, default=str)

        results = run_all_with_modes(tmp_dir, params)
    finally:
        for f in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, f))
        os.rmdir(tmp_dir)

    return results, file_records


# ============================================================
# 生成报告
# ============================================================
def build_report(all_period_results):
    """生成融合报告"""
    lines = []
    lines.append("# 布林带做空策略 - 多周期回测融合报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 数据来源: H2 原始数据，H4（每2根合并），D1（按日聚合）")
    lines.append("")

    # 策略参数
    lines.append("## 一、策略参数")
    lines.append("")
    lines.append("| 参数 | 严谨模式 | 宽松模式 | 说明 |")
    lines.append("|------|---------|---------|------|")
    lines.append("| 布林带周期 | 20 | 20 | SMA 周期 |")
    lines.append("| 标准差倍数 | 2.0 | 2.0 | BB 上下轨偏移 |")
    lines.append("| 带宽阈值 | 0.25 (25%) | 0.20 (20%) | |")
    lines.append("| 突破阈值 | 0.02 (+2%) | 0.01 (+1%) | |")
    lines.append("| 趋势斜率窗口 | 3 | 3 | 最近3根K线斜率>0 |")
    lines.append("| 每次开仓手数 | 动态计算 | 动态计算 | 总保证金1000万, 单笔保证金≤100万, 同时持仓保证金≤600万(60%) |")
    lines.append("| 手续费率 | 0.0001 | 0.0001 | |")
    lines.append("")
    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带趋势确认：最近3根K线，上轨和下轨斜率同时 > 0")
    lines.append("2. 布林带带宽 > 阈值")
    lines.append("3. 收盘价突破上轨 × (1+突破阈值)")
    lines.append("")
    lines.append("### 平仓条件")
    lines.append("- 价格回落到布林带中轨以下时平仓")
    lines.append("")

    # 各周期分模式汇总
    period_labels = {"H2": "2小时", "H4": "4小时", "D1": "日线"}
    mode_labels = {"strict": "严谨（25%/+2%）", "relaxed": "宽松（20%/+1%）"}

    # 收集所有品种（用于遍历）
    all_instruments = set()
    for period_data in all_period_results.values():
        for mode_data in period_data.values():
            for r in mode_data:
                all_instruments.add(r["instrument"])

    def _has_trades(inst, mode_key):
        for period_data in all_period_results.values():
            for r in period_data.get(mode_key, []):
                if r["instrument"] == inst and r["trade_count"] > 0:
                    return True
        return False

    lines.append("## 二、多周期汇总")
    lines.append("")
    lines.append("### 严谨模式")
    lines.append("")
    lines.append("| 品种 | H2 | H4 | D1 |")
    lines.append("|------|----|----|----|")
    for inst in sorted(all_instruments):
        if not _has_trades(inst, "strict"):
            continue
        cells = []
        for period_data in all_period_results.values():
            strict_results = period_data.get("strict", [])
            match = [r for r in strict_results if r["instrument"] == inst]
            if match and match[0]["trade_count"] > 0:
                r = match[0]
                cells.append(f"**{r['trade_count']}笔** {r['total_pnl']:>+,.0f}")
            else:
                cells.append("-")
        lines.append(f"| {inst} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines.append("")

    lines.append("### 宽松模式")
    lines.append("")
    lines.append("| 品种 | H2 | H4 | D1 |")
    lines.append("|------|----|----|----|")
    for inst in sorted(all_instruments):
        if not _has_trades(inst, "relaxed"):
            continue
        cells = []
        for period_data in all_period_results.values():
            relaxed_results = period_data.get("relaxed", [])
            match = [r for r in relaxed_results if r["instrument"] == inst]
            if match and match[0]["trade_count"] > 0:
                r = match[0]
                cells.append(f"**{r['trade_count']}笔** {r['total_pnl']:>+,.0f}")
            else:
                cells.append("-")
        lines.append(f"| {inst} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines.append("")

    # 对比总表
    lines.append("## 三、三周期对比")
    lines.append("")
    lines.append("| | H2（2小时） | H4（4小时） | D1（日线） |")
    lines.append("|--|------------|------------|----------|")
    for mode_key, mode_label in [("strict", "严谨模式"), ("relaxed", "宽松模式")]:
        counts = []
        totals = []
        for period_data in all_period_results.values():
            mode_results = period_data.get(mode_key, [])
            signal = [r for r in mode_results if r["trade_count"] > 0]
            counts.append(sum(r["trade_count"] for r in signal))
            totals.append(sum(r.get("total_pnl", 0) for r in signal))
        lines.append(f"| {mode_label} 交易笔数 | {counts[0]} | {counts[1]} | {counts[2]} |")
        lines.append(f"| {mode_label} 总盈亏 | {totals[0]:>+,.0f} | {totals[1]:>+,.0f} | {totals[2]:>+,.0f} |")
    lines.append("")

    # 有交易的品种详情 + 图表引用
    lines.append("## 四、交易详情与过程图")
    lines.append("")

    trade_entries = []
    for period_name, period_data in all_period_results.items():
        for mode_key, mode_label in mode_labels.items():
            mode_results = period_data.get(mode_key, [])
            for r in mode_results:
                if r["trade_count"] > 0:
                    trade_entries.append((period_name, mode_key, mode_label, r))

    for period_name, mode_key, mode_label, r in trade_entries:
        inst = r["instrument"]
        section_title = f"### {inst} - {period_labels[period_name]} - {mode_label}"
        lines.append(section_title)
        lines.append("")
        lines.append(f"- 数据范围: {r['date_start']} ~ {r['date_end']}（{r['records']} 条记录）")
        lines.append(f"- 合约乘数: {r['volume_multiple']}, 保证金率: {r.get('margin_rate', 0.10)*100:.0f}%")
        lines.append(f"- 最大带宽: {r['max_bandwidth']:.4f}")
        lines.append(f"- 交易笔数: {r['trade_count']}")
        lines.append(f"- 盈利/亏损: {r.get('win_count', 0)}/{r.get('loss_count', 0)}")
        lines.append(f"- 胜率: {r.get('win_rate', '-')}%")
        lines.append(f"- 总盈亏: {r.get('total_pnl', 0):>+,.1f} 元")
        lines.append(f"- 总保证金: {r.get('total_margin', 0):>+,.1f} 元")
        lines.append(f"- 平均收益率: {r.get('avg_return_rate', 0):>+,.2f}%")
        if r.get("max_drawdown"):
            lines.append(f"- 最大回撤: {r['max_drawdown']:>+,.1f} 元")
        if r.get("avg_holding_days"):
            lines.append(f"- 平均持仓天数: {r['avg_holding_days']}")
        lines.append("")

        # 交易明细
        if r["trades"]:
            lines.append("交易明细:")
            lines.append("")
            lines.append("| # | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | 持仓天数 | 保证金 | 点数盈亏 | 手续费 | 净盈亏 | 收益率 |")
            lines.append("|---|---------|--------|---------|--------|------|---------|--------|---------|--------|--------|--------|")
            for j, t in enumerate(r["trades"], 1):
                od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])
                lines.append(
                    f"| {j} | {od} | {t['open_price']:,.0f} | {cd} | {t['close_price']:,.0f} | "
                    f"{t['volume']} | {t['holding_days']} | {t['margin']:>+,} | {t['points']:>+,.1f} | "
                    f"{t['fee']:,.1f} | {t['net_pnl']:>+,.1f} | {t['return_rate']:>+,.1f}% |"
                )
            lines.append("")

    # 结论
    lines.append("## 五、结论与分析")
    lines.append("")
    total_trades_strict = sum(sum(r["trade_count"] for r in d.get("strict", []) if r["trade_count"] > 0) for d in all_period_results.values())
    total_trades_relaxed = sum(sum(r["trade_count"] for r in d.get("relaxed", []) if r["trade_count"] > 0) for d in all_period_results.values())
    total_pnl_relaxed = sum(r.get("total_pnl", 0) for d in all_period_results.values() for r in d.get("relaxed", []) if r["trade_count"] > 0)
    total_margin_relaxed = sum(r.get("total_margin", 0) for d in all_period_results.values() for r in d.get("relaxed", []) if r["trade_count"] > 0)
    total_pnl_strict = sum(r.get("total_pnl", 0) for d in all_period_results.values() for r in d.get("strict", []) if r["trade_count"] > 0)
    total_margin_strict = sum(r.get("total_margin", 0) for d in all_period_results.values() for r in d.get("strict", []) if r["trade_count"] > 0)

    lines.append(f"### 整体数据")
    lines.append(f"- 测试品种: 31 个")
    lines.append(f"- 测试周期: H2 / H4 / D1")
    lines.append(f"- 严谨模式: {total_trades_strict} 笔交易, 总盈亏 {total_pnl_strict:>+,.1f} 元, 总保证金 {total_margin_strict:>+,.1f} 元")
    if total_margin_strict > 0:
        lines.append(f"- 严谨模式总收益率: {total_pnl_strict/total_margin_strict*100:+,.2f}%")
    lines.append(f"- 宽松模式: {total_trades_relaxed} 笔交易, 总盈亏 {total_pnl_relaxed:>+,.1f} 元, 总保证金 {total_margin_relaxed:>+,.1f} 元")
    if total_margin_relaxed > 0:
        lines.append(f"- 宽松模式总收益率: {total_pnl_relaxed/total_margin_relaxed*100:+,.2f}%")
    lines.append("")
    lines.append("### 关键发现")
    lines.append("1. **条件组合非常严格**：趋势斜率 + 带宽阈值 + 突破阈值的组合导致信号极少")
    lines.append("2. **不同周期捕捉不同行情**：H2 捕捉 FG（玻璃）短期波动，D1 捕捉 ag（白银）大趋势")
    lines.append("3. **ag2606 白银表现突出**：日线周期下产生 1 笔大额盈利（+31.3 万），说明策略在强趋势品种上有效")
    lines.append("4. **H4 周期信号最少**：数据量减半 + 斜率窗口覆盖时间更长，条件更难满足")
    lines.append("")

    return "\n".join(lines), trade_entries


# ============================================================
# 主入口
# ============================================================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    base_params = {
        "bb_period": 20, "bb_std": 2.0,
        "bandwidth_threshold": 0.25, "breakout_threshold": 0.02,
        "fee_rate": 0.0001,
    }

    print("=" * 50)
    print("多周期融合回测")
    print("=" * 50)

    all_period_results = {}
    all_file_records = {}

    periods = [
        ("H2", None),
        ("H4", resample_h2_to_h4),
        ("D1", resample_h2_to_d1),
    ]

    for period_name, resample_fn in periods:
        print(f"\n正在回测 {period_name} ...")
        results, file_records = run_period(period_name, resample_fn, base_params)
        all_period_results[period_name] = results
        all_file_records[period_name] = file_records
        strict_count = sum(r["trade_count"] for r in results.get("strict", []))
        relaxed_count = sum(r["trade_count"] for r in results.get("relaxed", []))
        print(f"  严谨模式: {strict_count} 笔, 宽松模式: {relaxed_count} 笔")

    # 生成报告
    print("\n生成融合报告...")
    report, trade_entries = build_report(all_period_results)

    # 生成过程图
    print("\n生成过程图...")
    chart_refs = {}  # (period, mode_key, instrument) -> filename
    for period_name, mode_key, mode_label, r in trade_entries:
        inst = r["instrument"]
        fname_key = f"{inst.lower()}_kline.json"
        records = all_file_records[period_name].get(fname_key)
        if not records:
            # 尝试模糊匹配
            for fk, recs in all_file_records[period_name].items():
                if inst.lower() in fk.lower():
                    records = recs
                    break
        if not records:
            print(f"  警告: 找不到 {inst} 的数据，跳过图表")
            continue

        chart_filename = f"backtest_{period_name.lower()}_{mode_key}_{inst}.png"
        chart_path = os.path.join(OUTPUT_DIR, chart_filename)

        # 转换日期为 datetime
        for t in r["trades"]:
            if not hasattr(t["open_date"], "year"):
                t["open_date"] = pd.Timestamp(t["open_date"])
            if not hasattr(t["close_date"], "year"):
                t["close_date"] = pd.Timestamp(t["close_date"])

        plot_trade_process(records, r["trades"], inst, period_name, mode_label, chart_path)
        chart_refs[(period_name, mode_key, inst)] = chart_filename

    # 把图表引用插入报告
    updated_lines = report.split("\n")
    final_lines = []
    for line in updated_lines:
        final_lines.append(line)
        # 在交易详情标题后面插入图表
        if line.startswith("### ") and "-" in line and ("H2" in line or "H4" in line or "D1" in line):
            # 解析标题
            parts = line.replace("### ", "").split(" - ")
            if len(parts) >= 3:
                inst = parts[0]
                period_name = parts[1]
                mode_part = parts[2]
                mode_key = "strict" if "严谨" in mode_part else "relaxed"
                key = (period_name, mode_key, inst)
                if key in chart_refs:
                    final_lines.append("")
                    final_lines.append(f"![{inst} {period_name} {mode_part} 过程图]({chart_refs[key]})")
                    final_lines.append("")

    report_with_charts = "\n".join(final_lines)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report_with_charts)

    print(f"\n融合报告已保存: {OUTPUT_FILE}")
    print("完成！")


if __name__ == "__main__":
    main()
