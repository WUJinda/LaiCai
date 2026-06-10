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
    _BANDWIDTH_DATA, get_bandwidth_threshold, get_bandwidth_percentile,
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
    """双顶状态机回测，返回 (trades, bbands, monitoring, scan_events, threshold)

    状态机：
      IDLE → WAITING_PULLBACK → LEFT_PEAK_FOUND → IN_POSITION
      - monitoring 只在 LEFT_PEAK_FOUND/IN_POSITION 时为 True
      - scan_events 记录每次完整扫描事件（找到左峰的窗口才记录）
    """
    bb_period = params["bb_period"]
    bb_std = params["bb_std"]
    volume_multiple = params["volume_multiple"]
    margin_rate = params["margin_rate"]
    threshold = params["bandwidth_threshold"]
    lookback = params.get("left_peak_lookback", 30)
    zone_lo = params.get("zone_lower", 0.99)
    zone_up = params.get("zone_upper", 1.02)

    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, bb_period, bb_std
    )

    close_vals = df["close"].values
    high_vals = df["high"].values
    n = len(df)
    trades = []
    open_trade = None
    monitoring = np.zeros(n, dtype=bool)
    scan_events = []  # 完成的扫描事件列表
    current_scan = None  # 当前进行中的扫描事件
    current_margin = 0
    trend_slope_window = 3

    # 状态机
    STATE_IDLE = 0
    STATE_WAITING_PULLBACK = 1
    STATE_LEFT_PEAK_FOUND = 2
    STATE_IN_POSITION = 3
    state = STATE_IDLE
    h_left = 0.0
    h_left_idx = -1
    search_start = 0
    entry_bar_count = 0

    for i in range(bb_period, n):
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
        conditions_met = trend_confirmed and bw_ok
        close = close_vals[i]
        bb_middle = middle[i]

        # ====================================================
        # 持仓中 → 只看止盈
        # ====================================================
        if state == STATE_IN_POSITION:
            monitoring[i] = True  # 持仓期间保持窗口可见
            if close <= bb_middle:
                open_trade.close(i, df["date"].iloc[i], close)
                current_margin -= (open_trade.open_price * volume_multiple
                                   * margin_rate * open_trade.volume)
                trades.append(open_trade)
                open_trade = None
                # 结束扫描事件
                if current_scan is not None:
                    current_scan["end_idx"] = i
                    current_scan["outcome"] = "closed"
                    scan_events.append(current_scan)
                    current_scan = None
                state = STATE_IDLE
                h_left = 0.0
                h_left_idx = -1
            continue

        # ====================================================
        # 空仓 → 状态机
        # ====================================================

        # IDLE → WAITING_PULLBACK：带宽+trend 达标
        if state == STATE_IDLE:
            if conditions_met:
                state = STATE_WAITING_PULLBACK
            monitoring[i] = False

        # WAITING_PULLBACK → 等价格回到中轨；条件消失则回 IDLE
        elif state == STATE_WAITING_PULLBACK:
            if not conditions_met:
                state = STATE_IDLE
                monitoring[i] = False
            elif close <= bb_middle:
                # 回溯 lookback 根K线找左峰
                search_start = max(0, i - lookback + 1)
                window_highs = high_vals[search_start:i + 1]
                max_offset = int(np.argmax(window_highs))
                h_left = float(window_highs[max_offset])
                h_left_idx = search_start + max_offset

                state = STATE_LEFT_PEAK_FOUND
                entry_bar_count = 0
                monitoring[i] = True

                # 开始新的扫描事件
                current_scan = {
                    "pullback_idx": i,
                    "peak_idx": h_left_idx,
                    "peak_price": h_left,
                    "entry_idx": None,
                    "end_idx": -1,
                    "outcome": "",
                }
            else:
                monitoring[i] = False  # 等待中，不显示

        # LEFT_PEAK_FOUND → 等价格进入入场区间
        elif state == STATE_LEFT_PEAK_FOUND:
            entry_bar_count += 1
            monitoring[i] = True

            # 超时退出
            if entry_bar_count > lookback:
                if current_scan is not None:
                    current_scan["end_idx"] = i
                    current_scan["outcome"] = "timeout"
                    scan_events.append(current_scan)
                    current_scan = None
                state = STATE_IDLE
                h_left = 0.0
                h_left_idx = -1
                monitoring[i] = False
                continue

            # 价格突破区间上沿 → 形态失效
            if close > h_left * zone_up:
                if current_scan is not None:
                    current_scan["end_idx"] = i
                    current_scan["outcome"] = "invalidation"
                    scan_events.append(current_scan)
                    current_scan = None
                state = STATE_IDLE
                h_left = 0.0
                h_left_idx = -1
                monitoring[i] = False
                continue

            # 价格进入入场区间 → 做空（双顶入场）
            if h_left * zone_lo <= close <= h_left * zone_up:
                margin_per_lot = close * volume_multiple * margin_rate
                max_by_trade = (int(MAX_PER_TRADE // margin_per_lot)
                                if margin_per_lot > 0 else 0)
                remaining = MAX_TOTAL_EXPOSURE - current_margin
                max_by_total = (int(remaining // margin_per_lot)
                                if margin_per_lot > 0 else 0)
                volume = min(max_by_trade, max_by_total)

                if volume > 0:
                    open_trade = Trade(
                        i, df["date"].iloc[i], close, volume,
                        h_left=h_left, h_left_idx=h_left_idx,
                        scan_start_idx=search_start, scan_end_idx=i,
                        zone_upper=h_left * zone_up,
                        bb_middle_at_entry=bb_middle,
                    )
                    current_margin += close * volume_multiple * margin_rate * volume
                    state = STATE_IN_POSITION
                    if current_scan is not None:
                        current_scan["entry_idx"] = i
                        # 事件窗口在平仓时结束，不在此处关闭

    # 未平仓的交易：不加入 trades（calc_trade_pnl 要求 close_price 非空）
    # 但记录到 scan_events 以便可视化
    if open_trade is not None:
        if current_scan is not None:
            current_scan["end_idx"] = n - 1
            current_scan["outcome"] = "open"
            scan_events.append(current_scan)

    bbands = {
        "upper": upper, "middle": middle,
        "lower": lower, "bandwidth": bandwidth,
    }
    return trades, bbands, monitoring, scan_events, threshold


def run_period(period_name):
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
        bw_threshold = get_bandwidth_threshold(instrument, period_name)

        params = {
            "bb_period": 20, "bb_std": 2.0,
            "volume_multiple": vm, "margin_rate": mr,
            "bandwidth_threshold": bw_threshold,
            "fee_rate": 0.0001,
            "left_peak_lookback": 30,
            "zone_lower": 0.99,
            "zone_upper": 1.02,
        }

        trades, bbands, monitoring, scan_events, actual_threshold = run_single_with_monitoring(df, params)
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
            "percentile_used": get_bandwidth_percentile(instrument, period_name),
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
            "_scan_events": scan_events,
            "_trades_raw": trades,
            "_zone_lower": params["zone_lower"],
            "_zone_upper": params["zone_upper"],
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


# ============================================================
# 图表生成（带扫描窗口标注）
# ============================================================
def plot_trade_chart(result, output_path):
    """绘制交易过程图：OHLC + BB + 扫描窗口 + 左峰 + 开平仓标记"""
    df = result["_df"]
    bbands = result["_bbands"]
    scan_events = result.get("_scan_events", [])
    trades = result["trades"]
    trades_raw = result.get("_trades_raw", [])
    instrument = result["instrument"]
    period = result["kline_style"]
    threshold = result["bw_threshold"]

    upper = bbands["upper"]
    middle = bbands["middle"]
    lower = bbands["lower"]
    bandwidth = bbands["bandwidth"]

    # 匹配交易详情 ↔ 原始 Trade 对象
    trade_info = []
    for td, tr in zip(trades, trades_raw):
        open_date = pd.Timestamp(td["open_date"])
        close_date = pd.Timestamp(td["close_date"])
        open_matches = df.index[df["date"] == open_date]
        close_matches = df.index[df["date"] == close_date]
        if len(open_matches) > 0 and len(close_matches) > 0:
            trade_info.append((open_matches[0], close_matches[0], td, tr))
    if not trade_info:
        return

    # 截取显示区域：从最早扫描窗口的峰值前10根 ~ 最晚平仓后10根
    # 找与交易关联的 scan_events
    trade_scan_map = {}  # open_idx → scan_event
    for ti in trade_info:
        open_idx = ti[0]
        for evt in scan_events:
            if evt.get("entry_idx") == open_idx:
                trade_scan_map[open_idx] = evt
                break

    earliest_idx = min(
        min(t[0] for t in trade_info),
        min((trade_scan_map[t[0]].get("peak_idx", t[0]) for t in trade_info
             if t[0] in trade_scan_map), default=trade_info[0][0])
    )
    latest_close = max(t[1] for t in trade_info)
    start_idx = max(0, earliest_idx - 15)
    end_idx = min(len(df) - 1, latest_close + 10)

    df_slice = df.iloc[start_idx:end_idx + 1].copy().reset_index(drop=True)
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
    ax1.plot(x, middle_slice, "b-", linewidth=1.2, alpha=0.8, label="中轨")
    ax1.plot(x, lower_slice, "g--", linewidth=0.8, alpha=0.7, label="下轨")

    # --- 扫描窗口 + 左峰 + 入场区间 ---
    zone_lo_mult = result.get("_zone_lower", 0.99)
    zone_up_mult = result.get("_zone_upper", 1.02)

    for j, (open_idx, close_idx, td, tr) in enumerate(trade_info):
        ox = open_idx - start_idx
        cx = close_idx - start_idx
        open_price = td["open_price"]
        close_price = td["close_price"]
        h_left = getattr(tr, "h_left", None)
        h_left_idx_abs = getattr(tr, "h_left_idx", -1)
        scan_start_abs = getattr(tr, "scan_start_idx", -1)
        scan_end_abs = getattr(tr, "scan_end_idx", -1)
        evt = trade_scan_map.get(open_idx)

        # ---- 扫描窗口底色（从回踩中轨到窗口结束）----
        if evt is not None:
            pb_abs = evt["pullback_idx"]
            end_abs = evt["end_idx"] if evt["end_idx"] >= 0 else close_idx
            pk_abs = evt["peak_idx"]
            pb_x = pb_abs - start_idx
            end_x = end_abs - start_idx

            if end_x > pb_x and 0 <= pb_x < n:
                # 金色底色：回踩中轨 → 窗口结束
                ax1.axvspan(pb_x - 0.5, end_x + 0.5, alpha=0.12, color="gold", zorder=0)
                ax2.axvspan(pb_x - 0.5, end_x + 0.5, alpha=0.12, color="gold", zorder=0)

                # 回踩中轨竖线（扫描起点）
                ax1.axvline(x=pb_x, color="darkorange", linewidth=2.0,
                            linestyle="-", alpha=0.8, zorder=3)
                pb_date = df_slice["date"].iloc[pb_x]
                fmt_dt = "%m-%d" if period in ("H2", "H4") else "%Y-%m-%d"
                mid_val = middle_slice[pb_x]
                ax1.annotate(
                    f">> 回踩中轨\n   扫描起点\n   {pb_date.strftime(fmt_dt)}",
                    (pb_x, mid_val),
                    textcoords="offset points", xytext=(12, -15), fontsize=7,
                    fontweight="bold", color="darkorange", ha="left",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow",
                              edgecolor="darkorange", alpha=0.9),
                )

                # 左峰星标
                pk_x = pk_abs - start_idx
                if 0 <= pk_x < n and h_left is not None:
                    ax1.scatter(pk_x, h_left, marker="*", color="darkorange", s=350,
                                zorder=10, edgecolors="brown", linewidths=1.5,
                                label="H_left(左峰)" if j == 0 else "")
                    pk_date = df_slice["date"].iloc[pk_x].strftime(fmt_dt)
                    ax1.annotate(
                        f"H_left\n{h_left:,.0f}\n{pk_date}",
                        (pk_x, h_left),
                        textcoords="offset points", xytext=(0, 25), fontsize=8,
                        fontweight="bold", color="darkorange", ha="center",
                        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                                  edgecolor="darkorange", alpha=0.9),
                        arrowprops=dict(arrowstyle="->", color="darkorange", lw=1.0),
                    )

                    # 左峰水平虚线
                    line_left = max(0, pk_x)
                    line_right = min(n - 1, end_x + 2)
                    ax1.hlines(h_left, line_left, line_right,
                               colors="orange", linewidth=1.5,
                               linestyles="--", alpha=0.6)
                    # 入场区间上下沿
                    zone_l = h_left * zone_lo_mult
                    zone_u = h_left * zone_up_mult
                    ax1.hlines(zone_l, line_left, line_right,
                               colors="brown", linewidth=0.7, linestyles=":", alpha=0.5)
                    ax1.hlines(zone_u, line_left, line_right,
                               colors="brown", linewidth=0.7, linestyles=":", alpha=0.5)
                    ax1.annotate(
                        f"入场 [{zone_l:,.0f}, {zone_u:,.0f}]",
                        (line_right, zone_l),
                        textcoords="offset points", xytext=(-5, -12),
                        fontsize=6, color="brown", alpha=0.8, ha="right",
                    )

        # ---- 开仓点 ▼ ----
        ax1.scatter(ox, open_price, marker="v", color="red", s=150, zorder=5,
                    edgecolors="darkred", linewidths=1.5)
        ax1.annotate(f"开{j+1}\n{open_price:,.0f}", (ox, open_price),
                     textcoords="offset points", xytext=(10, -30), fontsize=8,
                     color="darkred",
                     arrowprops=dict(arrowstyle="->", color="darkred", lw=0.8))

        # ---- 平仓点 ▲ ----
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
        pnl = td.get("net_pnl", 0)
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
        Line2D([0], [0], color="b", linestyle="-", label="中轨"),
        Line2D([0], [0], color="g", linestyle="--", label="下轨"),
        Line2D([0], [0], marker="v", color="red", linestyle="None", label="开空仓", markersize=8),
        Line2D([0], [0], marker="^", color="limegreen", linestyle="None", label="平空仓", markersize=8),
        Line2D([0], [0], marker="*", color="darkorange", linestyle="None", label="H_left(左峰)", markersize=12),
        Rectangle((0, 0), 1, 1, facecolor="gold", alpha=0.3, label="扫描窗口"),
    ]
    ax1.legend(handles=legend_elements, loc="upper left", fontsize=9)
    ax1.set_title(
        f"{instrument} {period} — 双顶查表法({result['percentile_used']}) 阈值={threshold:.4f}",
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
    lines.append("# 双顶查表法带宽阈值回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 阈值来源: bandwidth_stats.json，各品种各周期独立统计")
    lines.append(f"> 百分位选择：按 CV/偏度 自动选 P75/P80/P85/P90")
    lines.append("")

    # 阈值表
    lines.append("## 一、各品种各周期带宽阈值")
    lines.append("")
    lines.append("| 品种 | H2 | H4 | D1 | 百分位(H2/H4/D1) |")
    lines.append("|------|-----|-----|-----|------------------|")
    for key in sorted(_BANDWIDTH_DATA.keys()):
        parts = key.rsplit("_", 1)
        if len(parts) != 2:
            continue
        sym = parts[0]
        if "_" in sym:
            continue
        # 每个品种只输出一行
        h2_key = f"{sym}_H2"
        if h2_key != key:
            continue
        h2_v = _BANDWIDTH_DATA.get(h2_key, {}).get("threshold", 0)
        h4_v = _BANDWIDTH_DATA.get(f"{sym}_H4", {}).get("threshold", 0)
        d1_v = _BANDWIDTH_DATA.get(f"{sym}_D1", {}).get("threshold", 0)
        h2_pct = _BANDWIDTH_DATA.get(h2_key, {}).get("percentile", "P75")
        h4_pct = _BANDWIDTH_DATA.get(f"{sym}_H4", {}).get("percentile", "P75")
        d1_pct = _BANDWIDTH_DATA.get(f"{sym}_D1", {}).get("percentile", "P75")
        pcts = f"{h2_pct}/{h4_pct}/{d1_pct}" if not (h2_pct == h4_pct == d1_pct) else h2_pct
        lines.append(f"| {sym} | {h2_v:.4f} | {h4_v:.4f} | {d1_v:.4f} | {pcts} |")
    lines.append("")

    # 策略条件
    lines.append("## 二、策略条件")
    lines.append("")
    lines.append("### 开仓条件（做空）")
    lines.append("1. 布林带趋势确认：最近3根K线，上轨和下轨斜率同时 > 0")
    lines.append("2. 布林带带宽 > 该品种该周期查表阈值")
    lines.append("3. 等待价格回到布林带中轨 → 回溯30根K线找左峰 H_left")
    lines.append("4. 价格进入入场区间 [0.99×H_left, 1.02×H_left] → 做空")
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
            lines.append(f"- 扫描占比: {r['monitoring_pct']:.1f}% 的K线处于扫描/持仓状态")
            lines.append(f"- 合约乘数: {r['volume_multiple']}, 保证金率: {r['margin_rate']*100:.0f}%")
            lines.append("")
            lines.append(f"![{inst} {pname} 过程图]({chart_filename})")
            lines.append("")

            # 交易明细表
            lines.append("| # | 扫描起点 | H_left | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | 持仓天 | 保证金 | 净盈亏 | 收益率 |")
            lines.append("|---|---------|--------|---------|--------|---------|--------|------|--------|--------|--------|--------|")

            df = r["_df"]
            raw_trades = r.get("_trades_raw", [])

            for j, (t, tr) in enumerate(zip(r["trades"], raw_trades), 1):
                od = t["open_date"].strftime("%Y-%m-%d") if hasattr(t["open_date"], "strftime") else str(t["open_date"])
                cd = t["close_date"].strftime("%Y-%m-%d") if hasattr(t["close_date"], "strftime") else str(t["close_date"])

                # 扫描起点（从 Trade 对象获取）
                scan_end = getattr(tr, "scan_end_idx", -1)
                h_left_val = getattr(tr, "h_left", None)
                if scan_end >= 0 and scan_end < len(df):
                    scan_date = df["date"].iloc[scan_end].strftime("%Y-%m-%d")
                    scan_label = f"{scan_date}"
                else:
                    scan_label = "-"
                h_left_str = f"{h_left_val:,.0f}" if h_left_val else "-"

                lines.append(
                    f"| {j} | {scan_label} | {h_left_str} | {od} | {t['open_price']:,.0f} | {cd} "
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

    print("=" * 60)
    print("双顶查表法带宽阈值回测")
    print("  策略: 带宽达标 → 等价格回到中轨 → 回溯30根找左峰")
    print("  入场: 价格进入 [0.99×H_left, 1.02×H_left]")
    print("  百分位: 按品种×周期自动选择 P75/P80/P85/P90")
    print("=" * 60)

    all_results = {}
    for pname in ["H2", "H4", "D1"]:
        print(f"\n回测 {pname} ...", flush=True)
        results = run_period(pname)
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
