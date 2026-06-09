# -*- coding: utf-8 -*-
"""
查表法带宽阈值回测（修正版）
- 各品种各周期使用对应P75阈值
- ag（白银）使用P90，其余品种使用P75
- 输出交易详情 + 监控窗口标注 + 图表
"""
import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from _batch_backtest import (
    calc_bbands, Trade, calc_trade_pnl,
    get_multiplier, get_margin_rate,
    TOTAL_CAPITAL, MAX_PER_TRADE, MAX_TOTAL_EXPOSURE,
    _BANDWIDTH_DATA, _P90_INSTRUMENTS,
)

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
DATA_DIRS = {
    "H2": os.path.join(DESKTOP, "quanda_exports_h2"),
    "H4": os.path.join(DESKTOP, "quanda_exports_h4"),
    "D1": os.path.join(DESKTOP, "quanda_exports_d1"),
}
OUTPUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "results", "band_lookup"
))

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# 回测（带监控窗口追踪）
# ============================================================
def run_single_with_monitoring(df, params):
    """回测并返回 (trades, bbands, monitoring_array, threshold_used)"""
    bb_period = params["bb_period"]
    bb_std = params["bb_std"]
    volume_multiple = params["volume_multiple"]
    margin_rate = params["margin_rate"]
    threshold = params["bandwidth_threshold"]
    breakout_threshold = params["breakout_threshold"]

    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, bb_period, bb_std
    )

    close_vals = df["close"].values
    trades = []
    open_trade = None
    monitoring = np.zeros(len(df), dtype=bool)
    trend_slope_window = 3
    current_margin = 0

    for i in range(bb_period, len(df)):
        if np.isnan(upper[i]) or np.isnan(middle[i]):
            continue

        # 斜率趋势确认
        if i >= bb_period + trend_slope_window - 1:
            upper_slope = (upper[i] - upper[i - trend_slope_window]) / (trend_slope_window - 1)
            lower_slope = (lower[i] - lower[i - trend_slope_window]) / (trend_slope_window - 1)
            trend_confirmed = upper_slope > 0 and lower_slope > 0
        else:
            trend_confirmed = False

        bw_ok = bandwidth[i] > threshold
        is_monitoring = trend_confirmed and bw_ok
        monitoring[i] = is_monitoring

        # 平仓
        if open_trade is not None and close_vals[i] <= middle[i]:
            open_trade.close(i, df["date"].iloc[i], close_vals[i])
            current_margin -= (open_trade.open_price * volume_multiple
                               * margin_rate * open_trade.volume)
            trades.append(open_trade)
            open_trade = None

        # 开仓
        if open_trade is None and is_monitoring:
            breakout_price = upper[i] * (1 + breakout_threshold)
            if close_vals[i] > breakout_price:
                price = close_vals[i]
                margin_per_lot = price * volume_multiple * margin_rate
                max_by_trade = (int(MAX_PER_TRADE // margin_per_lot)
                                if margin_per_lot > 0 else 0)
                remaining = MAX_TOTAL_EXPOSURE - current_margin
                max_by_total = (int(remaining // margin_per_lot)
                                if margin_per_lot > 0 else 0)
                volume = min(max_by_trade, max_by_total)

                if volume > 0:
                    open_trade = Trade(i, df["date"].iloc[i], price, volume)
                    current_margin += price * volume_multiple * margin_rate * volume

    bbands = {
        "upper": upper, "middle": middle,
        "lower": lower, "bandwidth": bandwidth,
    }
    return trades, bbands, monitoring, threshold


def run_period(period_name, breakout_threshold=0.01):
    """跑一个周期的回测"""
    data_dir = DATA_DIRS[period_name]
    results = []

    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith("_kline.json"):
            continue
        filepath = os.path.join(data_dir, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)

        records = raw.get("data", [])
        if len(records) < 25:
            continue

        instrument = raw.get("instrument", fname.replace("_kline.json", ""))
        exchange = raw.get("exchange", "?")

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        vm = get_multiplier(instrument)
        mr = get_margin_rate(instrument)
        bw_threshold = _lookup_threshold(instrument, period_name)

        params = {
            "bb_period": 20, "bb_std": 2.0,
            "volume_multiple": vm, "margin_rate": mr,
            "bandwidth_threshold": bw_threshold,
            "breakout_threshold": breakout_threshold,
            "fee_rate": 0.0001,
        }

        trades, bbands, monitoring, actual_threshold = run_single_with_monitoring(df, params)
        trade_details = calc_trade_pnl(trades, vm, params["fee_rate"], mr)

        # 统计
        max_bw = float(np.nanmax(bbands["bandwidth"]))
        bw_above = float(np.nanmean(bbands["bandwidth"] > actual_threshold) * 100)
        monitoring_pct = float(np.mean(monitoring) * 100)

        result = {
            "instrument": instrument,
            "exchange": exchange,
            "kline_style": period_name,
            "records": len(df),
            "date_start": df["date"].iloc[0].strftime("%Y-%m-%d"),
            "date_end": df["date"].iloc[-1].strftime("%Y-%m-%d"),
            "max_bandwidth": round(max_bw, 4),
            "bw_threshold": round(actual_threshold, 6),
            "percentile_used": _get_percentile_label(instrument),
            "bw_above_pct": round(bw_above, 1),
            "monitoring_pct": round(monitoring_pct, 1),
            "volume_multiple": vm,
            "margin_rate": mr,
            "trade_count": len(trade_details),
            "trades": trade_details,
            # 额外数据供画图用
            "_monitoring": monitoring,
            "_bbands": bbands,
            "_df": df,
        }

        if trade_details:
            pnls = [t["net_pnl"] for t in trade_details]
            wins = sum(1 for t in trade_details if t["win"])
            result["total_pnl"] = round(sum(pnls), 2)
            result["win_count"] = wins
            result["loss_count"] = len(trade_details) - wins
            result["win_rate"] = round(wins / len(trade_details) * 100, 1)
            result["max_win"] = round(max(pnls), 2)
            result["max_loss"] = round(min(pnls), 2)
            result["avg_holding_days"] = round(
                sum(t["holding_days"] for t in trade_details) / len(trade_details), 1
            )
            cumulative = np.cumsum(pnls)
            peak = np.maximum.accumulate(cumulative)
            drawdown = cumulative - peak
            result["max_drawdown"] = round(float(drawdown.min()), 2)
            total_margin = sum(t["margin"] for t in trade_details)
            result["total_margin"] = round(total_margin, 2)
            result["avg_return_rate"] = round(
                sum(t["return_rate"] for t in trade_details) / len(trade_details), 2
            )

        results.append(result)

    return results


def _lookup_threshold(instrument_id, kline_style):
    """直接查表获取阈值（按品种代码长度降序，避免前缀冲突）"""
    sorted_items = sorted(
        _BANDWIDTH_DATA.items(),
        key=lambda x: len(x[0].rsplit("_", 1)[0]),
        reverse=True,
    )
    for key, vals in sorted_items:
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym, period = parts
            if instrument_id.upper().startswith(sym) and period == kline_style.upper():
                return vals["threshold"]
    return 0.04


def _get_percentile_label(instrument_id):
    """返回该品种使用的百分位标签"""
    for sym in _P90_INSTRUMENTS:
        if instrument_id.upper().startswith(sym):
            return "P90"
    return "P75"


# ============================================================
# 图表生成（带监控窗口标注）
# ============================================================
def plot_trade_chart(result, output_path):
    """绘制交易过程图：OHLC + BB + 监控窗口 + 开平仓标记"""
    df = result["_df"]
    bbands = result["_bbands"]
    monitoring = result["_monitoring"]
    trades = result["trades"]
    instrument = result["instrument"]
    period = result["kline_style"]
    threshold = result["bw_threshold"]

    upper = bbands["upper"]
    middle = bbands["middle"]
    lower = bbands["lower"]
    bandwidth = bbands["bandwidth"]

    # 匹配交易到 DataFrame 行索引
    trade_info = []
    for t in trades:
        open_date = pd.Timestamp(t["open_date"])
        close_date = pd.Timestamp(t["close_date"])
        open_matches = df.index[df["date"] == open_date]
        close_matches = df.index[df["date"] == close_date]
        if len(open_matches) > 0 and len(close_matches) > 0:
            # 找监控起始点：从开仓往前找到第一个 monitoring=True 的位置
            open_idx = open_matches[0]
            close_idx = close_matches[0]
            mon_start = open_idx
            for j in range(open_idx - 1, -1, -1):
                if monitoring[j]:
                    mon_start = j
                else:
                    break
            trade_info.append((mon_start, open_idx, close_idx, t))
    if not trade_info:
        return

    # 截取显示区域：首笔监控起始前10根 ~ 末笔平仓后10根
    earliest_mon = min(m for m, o, c, t in trade_info)
    latest_close = max(c for m, o, c, t in trade_info)
    start_idx = max(0, earliest_mon - 10)
    end_idx = min(len(df) - 1, latest_close + 10)

    df_slice = df.iloc[start_idx:end_idx + 1].copy().reset_index(drop=True)
    mon_slice = monitoring[start_idx:end_idx + 1]
    upper_slice = upper[start_idx:end_idx + 1]
    middle_slice = middle[start_idx:end_idx + 1]
    lower_slice = lower[start_idx:end_idx + 1]
    bw_slice = bandwidth[start_idx:end_idx + 1]
    n = len(df_slice)
    x = np.arange(n)

    fig_w = max(16, min(28, n * 0.2))
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(fig_w, 12),
        gridspec_kw={"height_ratios": [4, 1.5]},
    )

    # --- 监控窗口底色 ---
    mon_regions = []
    in_region = False
    region_start = 0
    for i in range(n):
        if mon_slice[i] and not in_region:
            region_start = i
            in_region = True
        elif not mon_slice[i] and in_region:
            mon_regions.append((region_start, i - 1))
            in_region = False
    if in_region:
        mon_regions.append((region_start, n - 1))

    for rs, re in mon_regions:
        ax1.axvspan(rs - 0.5, re + 0.5, alpha=0.12, color="gold", zorder=0)
        ax2.axvspan(rs - 0.5, re + 0.5, alpha=0.12, color="gold", zorder=0)

    # --- OHLC 蜡烛图 ---
    bar_width = 0.6
    for i in range(n):
        o = float(df_slice["open"].iloc[i])
        h = float(df_slice["high"].iloc[i])
        l = float(df_slice["low"].iloc[i])
        c = float(df_slice["close"].iloc[i])
        up = c >= o
        color = "#D32F2F" if up else "#388E3C"
        ax1.plot([i, i], [l, h], color=color, linewidth=0.5, zorder=1)
        body_bottom = min(o, c)
        body_height = abs(c - o)
        if body_height < 1e-6:
            body_height = max((h - l) * 0.01, 0.001)
        rect = Rectangle((i - bar_width / 2, body_bottom), bar_width, body_height,
                          facecolor=color, edgecolor=color, alpha=0.9, zorder=2)
        ax1.add_patch(rect)

    # --- 布林带 ---
    ax1.plot(x, upper_slice, "r--", linewidth=0.8, alpha=0.7, label="上轨")
    ax1.plot(x, middle_slice, "b--", linewidth=0.8, alpha=0.7, label="中轨")
    ax1.plot(x, lower_slice, "g--", linewidth=0.8, alpha=0.7, label="下轨")

    # --- 交易标记 ---
    for j, (mon_s, open_idx, close_idx, t) in enumerate(trade_info):
        sx = mon_s - start_idx        # 监控起始
        ox = open_idx - start_idx      # 开仓
        cx = close_idx - start_idx     # 平仓
        open_price = t["open_price"]
        close_price = t["close_price"]

        # 监控窗口标注
        ax1.annotate(f"监控{j+1}", (sx, upper_slice[sx]),
                     fontsize=7, color="orange", fontweight="bold",
                     ha="left", va="bottom")

        # 开仓点 ▼
        ax1.scatter(ox, open_price, marker="v", color="red", s=150, zorder=5,
                    edgecolors="darkred", linewidths=1.5)
        ax1.annotate(f"开{j+1}\n{open_price:,.0f}", (ox, open_price),
                     textcoords="offset points", xytext=(10, -30), fontsize=8,
                     color="darkred",
                     arrowprops=dict(arrowstyle="->", color="darkred", lw=0.8))

        # 平仓点 ▲
        ax1.scatter(cx, close_price, marker="^", color="limegreen", s=150, zorder=5,
                    edgecolors="darkgreen", linewidths=1.5)
        ax1.annotate(f"平{j+1}\n{close_price:,.0f}", (cx, close_price),
                     textcoords="offset points", xytext=(10, 20), fontsize=8,
                     color="darkgreen",
                     arrowprops=dict(arrowstyle="->", color="darkgreen", lw=0.8))

        # 开仓→平仓连线
        ax1.plot([ox, cx], [open_price, close_price], "r--", linewidth=1, alpha=0.5, zorder=3)
        ax1.axvspan(ox - 0.5, cx + 0.5, alpha=0.08, color="red")

        # 盈亏标注
        pnl = t.get("net_pnl", 0)
        mid_x = (ox + cx) / 2
        mid_price = (open_price + close_price) / 2
        pnl_color = "darkgreen" if pnl > 0 else "darkred"
        ax1.annotate(
            f"{'盈利' if pnl > 0 else '亏损'} {pnl:+,.0f}",
            (mid_x, mid_price), fontsize=9, fontweight="bold",
            ha="center", va="bottom", color=pnl_color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.7),
        )

    legend_elements = [
        Line2D([0], [0], color="r", linestyle="--", label="上轨"),
        Line2D([0], [0], color="b", linestyle="--", label="中轨"),
        Line2D([0], [0], color="g", linestyle="--", label="下轨"),
        Line2D([0], [0], marker="v", color="red", linestyle="None", label="开空仓", markersize=8),
        Line2D([0], [0], marker="^", color="limegreen", linestyle="None", label="平空仓", markersize=8),
        Rectangle((0, 0), 1, 1, facecolor="gold", alpha=0.3, label="监控窗口"),
    ]
    ax1.legend(handles=legend_elements, loc="upper left", fontsize=9)
    ax1.set_title(
        f"{instrument} {period} — 查表法({result['percentile_used']}) 阈值={threshold:.4f}",
        fontsize=13, fontweight="bold",
    )
    ax1.set_ylabel("价格")
    ax1.set_xlim(-1, n)
    ax1.grid(True, alpha=0.3)

    # --- 日期刻度 ---
    fmt = "%m-%d %H:%M" if period in ("H2", "H4") else "%Y-%m-%d"
    date_labels = [d.strftime(fmt) for d in df_slice["date"]]
    tick_step = max(1, n // 15)
    for ax in (ax1, ax2):
        ax.set_xticks(x[::tick_step])
        ax.set_xticklabels(date_labels[::tick_step], rotation=45, ha="right", fontsize=7)

    # --- 下图：带宽 ---
    ax2.fill_between(x, bw_slice, 0, alpha=0.3, color="steelblue")
    ax2.plot(x, bw_slice, color="steelblue", linewidth=0.8, label="带宽")
    ax2.axhline(y=threshold, color="red", linestyle="--", linewidth=1, alpha=0.8,
                label=f"阈值({result['percentile_used']}={threshold:.4f})")
    ax2.set_ylabel("带宽")
    ax2.set_xlim(-1, n)
    ax2.legend(fontsize=8, loc="upper right")
    ax2.grid(True, alpha=0.3)
    ax2.set_title("布林带带宽", fontsize=10)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表: {os.path.basename(output_path)}")


# ============================================================
# 报告生成
# ============================================================
def build_report(all_results):
    lines = []
    lines.append("# 查表法带宽阈值回测报告（修正版）")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 阈值来源: bandwidth_stats.json，各品种各周期独立统计")
    lines.append(f"> ag（白银）使用P90，其余品种使用P75")
    lines.append("")

    # 阈值表
    lines.append("## 一、各品种各周期带宽阈值")
    lines.append("")
    lines.append("| 品种 | H2 | H4 | D1 | 用的百分位 |")
    lines.append("|------|-----|-----|-----|-----------|")
    for key in sorted(_BANDWIDTH_DATA.keys()):
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        sym = parts[0]
        if "_" in sym:
            continue
        # 每个品种只输出一行
        vals = _BANDWIDTH_DATA[key]
        # 找该品种所有周期
        h2_key = f"{sym}_H2"
        h4_key = f"{sym}_H4"
        d1_key = f"{sym}_D1"
        if h2_key != key:
            continue
        h2_v = _BANDWIDTH_DATA.get(h2_key, {}).get("threshold", 0)
        h4_v = _BANDWIDTH_DATA.get(h4_key, {}).get("threshold", 0)
        d1_v = _BANDWIDTH_DATA.get(d1_key, {}).get("threshold", 0)
        pct = _BANDWIDTH_DATA.get(h2_key, {}).get("percentile", "P75")
        lines.append(f"| {sym} | {h2_v:.4f} | {h4_v:.4f} | {d1_v:.4f} | {pct} |")
    lines.append("")

    # 策略条件
    lines.append("## 二、策略条件")
    lines.append("")
    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带趋势确认：最近3根K线，上轨和下轨斜率同时 > 0")
    lines.append("2. 布林带带宽 > 该品种该周期查表阈值")
    lines.append("3. 收盘价突破上轨 × 1.01")
    lines.append("")
    lines.append("### 平仓条件")
    lines.append("- 价格回落到布林带中轨以下")
    lines.append("")
    lines.append("### 资金管理")
    lines.append("- 总敞口: 1000万, 单笔保证金 ≤ 100万, 同时持仓保证金 ≤ 600万")
    lines.append("")

    period_labels = {"H2": "2小时", "H4": "4小时", "D1": "日线"}

    # 汇总
    lines.append("## 三、各周期汇总")
    lines.append("")
    lines.append("| 周期 | 有交易品种 | 交易笔数 | 胜率 | 总盈亏 | 总保证金 | 收益率 |")
    lines.append("|------|-----------|---------|------|--------|---------|--------|")
    for pname, results in all_results.items():
        traded = [r for r in results if r["trade_count"] > 0]
        total_trades = sum(r["trade_count"] for r in traded)
        total_wins = sum(r.get("win_count", 0) for r in traded)
        total_pnl = sum(r.get("total_pnl", 0) for r in traded)
        total_margin = sum(r.get("total_margin", 0) for r in traded)
        wr = f"{total_wins/total_trades*100:.0f}%" if total_trades > 0 else "-"
        roi = f"{total_pnl/total_margin*100:+.2f}%" if total_margin > 0 else "-"
        lines.append(
            f"| {period_labels[pname]} | {len(traded)} | {total_trades} | {wr} "
            f"| {total_pnl:>+,.0f} | {total_margin:>+,.0f} | {roi} |"
        )
    lines.append("")

    # 各品种详情
    lines.append("## 四、各品种交易详情")
    lines.append("")
    for pname, results in all_results.items():
        traded = [r for r in results if r["trade_count"] > 0]
        if not traded:
            continue
        lines.append(f"### {period_labels[pname]}")
        lines.append("")
        lines.append("| 品种 | 阈值 | 百分位 | 笔数 | 胜率 | 总盈亏 | 保证金 | 收益率 | 回撤 | 均持仓天 |")
        lines.append("|------|------|--------|------|------|--------|--------|--------|------|---------|")
        for r in sorted(traded, key=lambda x: x.get("total_pnl", 0), reverse=True):
            wr = f"{r.get('win_rate', '-')}" if "win_rate" in r else "-"
            pnl = f"{r['total_pnl']:>+,.0f}" if "total_pnl" in r else "-"
            mg = f"{r['total_margin']:>+,.0f}" if "total_margin" in r else "-"
            rr = f"{r['avg_return_rate']:+.2f}%" if "avg_return_rate" in r else "-"
            dd = f"{r['max_drawdown']:>+,.0f}" if "max_drawdown" in r else "-"
            hd = f"{r['avg_holding_days']}" if "avg_holding_days" in r else "-"
            lines.append(
                f"| {r['instrument']} | {r['bw_threshold']:.4f} | {r['percentile_used']} "
                f"| {r['trade_count']} | {wr} | {pnl} | {mg} | {rr} | {dd} | {hd} |"
            )
        lines.append("")

    # 交易明细（带监控窗口）
    lines.append("## 五、交易明细（含监控窗口）")
    lines.append("")

    chart_count = 0
    for pname, results in all_results.items():
        for r in results:
            if r["trade_count"] == 0 or not r.get("trades"):
                continue

            chart_count += 1
            chart_filename = f"chart_{pname.lower()}_{r['instrument']}.png"
            chart_path = os.path.join(OUTPUT_DIR, chart_filename)

            inst = r["instrument"]
            lines.append(f"### {inst} ({period_labels[pname]})")
            lines.append(f"- 数据: {r['date_start']} ~ {r['date_end']} ({r['records']}条)")
            lines.append(f"- 阈值: {r['bw_threshold']:.4f} ({r['percentile_used']})")
            lines.append(f"- 监控占比: {r['monitoring_pct']:.1f}% 的K线处于监控状态")
            lines.append(f"- 合约乘数: {r['volume_multiple']}, 保证金率: {r['margin_rate']*100:.0f}%")
            lines.append("")
            lines.append(f"![{inst} {pname} 过程图]({chart_filename})")
            lines.append("")

            # 交易明细表
            lines.append("| # | 监控起始 | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | 持仓天 | 保证金 | 净盈亏 | 收益率 |")
            lines.append("|---|---------|---------|--------|---------|--------|------|--------|--------|--------|--------|")

            monitoring = r["_monitoring"]
            df = r["_df"]

            for j, t in enumerate(r["trades"], 1):
                od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])

                # 找监控起始日期
                open_ts = pd.Timestamp(t["open_date"])
                open_matches = df.index[df["date"] == open_ts]
                if len(open_matches) > 0:
                    oi = open_matches[0]
                    mon_start_idx = oi
                    for k in range(oi - 1, -1, -1):
                        if monitoring[k]:
                            mon_start_idx = k
                        else:
                            break
                    mon_date = df["date"].iloc[mon_start_idx].strftime("%Y-%m-%d")
                    mon_bars = oi - mon_start_idx
                    mon_label = f"{mon_date}({mon_bars}根)"
                else:
                    mon_label = "-"

                lines.append(
                    f"| {j} | {mon_label} | {od} | {t['open_price']:,.0f} | {cd} "
                    f"| {t['close_price']:,.0f} | {t['volume']} | {t['holding_days']} "
                    f"| {t['margin']:>+,.0f} | {t['net_pnl']:>+,.0f} | {t['return_rate']:>+,.1f}% |"
                )
            lines.append("")

            # 画图
            plot_trade_chart(r, chart_path)

    # 结论
    lines.append("## 六、结论")
    lines.append("")
    total_trades = 0
    total_pnl = 0
    total_margin = 0
    total_wins = 0
    for pname, results in all_results.items():
        for r in results:
            if r["trade_count"] > 0:
                total_trades += r["trade_count"]
                total_pnl += r.get("total_pnl", 0)
                total_margin += r.get("total_margin", 0)
                total_wins += r.get("win_count", 0)

    lines.append(f"- 总交易笔数: {total_trades}")
    lines.append(f"- 总盈亏: {total_pnl:>+,.0f} 元")
    lines.append(f"- 总保证金: {total_margin:>+,.0f} 元")
    if total_margin > 0:
        lines.append(f"- 总收益率: {total_pnl/total_margin*100:+.2f}%")
    if total_trades > 0:
        lines.append(f"- 整体胜率: {total_wins}/{total_trades} = {total_wins/total_trades*100:.1f}%")
    lines.append("")
    lines.append(f"- 共生成 {chart_count} 张交易过程图")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    breakout_threshold = 0.01

    print("=" * 60)
    print("查表法带宽阈值回测（修正版）")
    print(f"  ag（白银）用P90: {sorted(_P90_INSTRUMENTS)}")
    print(f"  其余品种用P75")
    print(f"  突破阈值: {breakout_threshold}")
    print("=" * 60)

    all_results = {}
    for pname in ["H2", "H4", "D1"]:
        print(f"\n回测 {pname} ...", flush=True)
        results = run_period(pname, breakout_threshold)
        traded = [r for r in results if r["trade_count"] > 0]
        total_pnl = sum(r.get("total_pnl", 0) for r in traded)
        total_trades = sum(r["trade_count"] for r in traded)
        print(f"  {pname}: {len(traded)} 个品种有交易, {total_trades} 笔, 盈亏 {total_pnl:>+,.0f}")
        all_results[pname] = results

    # 生成报告（包含画图）
    print("\n生成报告和图表...")
    report = build_report(all_results)

    report_path = os.path.join(OUTPUT_DIR, "backtest_band_lookup.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存: {report_path}")
    print("完成！")


if __name__ == "__main__":
    main()
