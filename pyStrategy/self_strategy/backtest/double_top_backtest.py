# -*- coding: utf-8 -*-
"""
双峰做空策略 — 独立回测脚本

策略逻辑：
  带宽 > 10% → 价格 ≤ 中轨(找左峰) → 价格进入 [0.99, 1.02]×H_left 区间 → 做空 → 中轨止盈

用法：
  python double_top_backtest.py                          # 批量回测所有品种（默认D1目录）
  python double_top_backtest.py --instrument rb2605      # 只回测指定品种
  python double_top_backtest.py --data-dir <path>        # 指定数据目录
  python double_top_backtest.py --no-chart               # 跳过图表生成
"""

import argparse
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


# ============================================================
# 资金管理常量
# ============================================================
TOTAL_CAPITAL = 10_000_000       # 总敞口资金
MAX_PER_TRADE = 1_000_000        # 单笔保证金上限 100万
MAX_TOTAL_EXPOSURE = 6_000_000   # 同时持仓保证金上限 600万

# 合约乘数表
MULTIPLIERS = {
    "rb": 10, "hc": 10, "cu": 5, "al": 5, "zn": 5,
    "ni": 1, "au": 1000, "ag": 15, "bu": 10, "ru": 10,
    "i": 100, "m": 10, "y": 10, "p": 10, "a": 10, "c": 10, "cs": 10,
    "SR": 10, "CF": 5, "RM": 10, "MA": 10, "TA": 5, "FG": 20, "SA": 20,
    "IC": 200, "IF": 300, "IH": 300, "IM": 200,
    "T": 10000, "TF": 10000, "TS": 20000,
}

# 保证金率表
MARGIN_RATES = {
    "rb": 0.10, "hc": 0.10, "cu": 0.10, "al": 0.10, "zn": 0.10,
    "ni": 0.12, "au": 0.10, "ag": 0.12, "bu": 0.10, "ru": 0.10,
    "i": 0.12, "m": 0.10, "y": 0.10, "p": 0.10, "a": 0.10, "c": 0.10, "cs": 0.10,
    "SR": 0.10, "CF": 0.10, "RM": 0.10, "MA": 0.10, "TA": 0.10, "FG": 0.10, "SA": 0.10,
    "IC": 0.12, "IF": 0.12, "IH": 0.12, "IM": 0.12,
    "T": 0.03, "TF": 0.03, "TS": 0.03,
}

# 默认参数
DEFAULT_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "bandwidth_min": 0.15,
    "left_peak_lookback": 30,
    "zone_lower": 0.99,
    "zone_upper": 1.02,
    "fee_rate": 0.0001,     # 单边万分之一
}

# 输出目录
OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs", "res")
)
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
DEFAULT_DATA_DIR = os.path.join(DESKTOP, "quanda_exports_d1")

# 状态码常量（与策略文件一致）
STATE_IDLE = 0
STATE_WAITING_PULLBACK = 1
STATE_LEFT_PEAK_FOUND = 2
STATE_IN_POSITION = 3

STATE_NAMES = {
    0: "空闲",
    1: "等待回调",
    2: "左峰确认",
    3: "持仓中",
}

# matplotlib 中文字体
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# 辅助函数
# ============================================================
def get_multiplier(instrument_id: str) -> int:
    for prefix, mult in MULTIPLIERS.items():
        if instrument_id.upper().startswith(prefix.upper()):
            return mult
    return 10


def get_margin_rate(instrument_id: str) -> float:
    for prefix, rate in MARGIN_RATES.items():
        if instrument_id.upper().startswith(prefix.upper()):
            return rate
    return 0.10


def calc_bbands(close_array, period=20, std_dev=2.0):
    """计算布林带 (upper, middle, lower, bandwidth)"""
    close = pd.Series(close_array.astype(float))
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = np.where(middle > 0, (upper - lower) / middle, 0)
    return upper.values, middle.values, lower.values, bandwidth


# ============================================================
# 交易记录类
# ============================================================
class Trade:
    def __init__(self, open_idx, open_date, open_price, volume,
                 h_left, h_left_idx, scan_start_idx, scan_end_idx,
                 zone_upper, bb_middle_at_entry, state_trace=None):
        self.open_idx = open_idx
        self.open_date = open_date
        self.open_price = open_price
        self.volume = volume
        self.h_left = h_left
        self.h_left_idx = h_left_idx          # 左峰在数据中的绝对索引
        self.scan_start_idx = scan_start_idx  # 30日扫描窗口起点
        self.scan_end_idx = scan_end_idx      # 30日扫描窗口终点（触发回调的bar）
        self.zone_upper = zone_upper
        self.bb_middle_at_entry = bb_middle_at_entry
        self.state_trace = state_trace or []  # 记录状态变化过程

        # 平仓信息（成交时填入）
        self.close_idx = None
        self.close_date = None
        self.close_price = None

    def close(self, close_idx, close_date, close_price):
        self.close_idx = close_idx
        self.close_date = close_date
        self.close_price = close_price


# ============================================================
# 单品种回测引擎
# ============================================================
def run_single_backtest(df, params, instrument_id="?"):
    """
    对单个品种的 DataFrame 运行双峰策略回测。

    参数:
        df: 包含 date/open/high/low/close 列的 DataFrame
        params: 策略参数字典
        instrument_id: 品种代码

    返回:
        trades: Trade 列表
        indicators: 指标数据字典
        state_log: 状态变化日志 [(bar_idx, old_state, new_state, note), ...]
    """
    p = params
    bb_period = p["bb_period"]
    bb_std = p["bb_std"]
    bandwidth_min = p["bandwidth_min"]
    lookback = p["left_peak_lookback"]
    zone_lower = p["zone_lower"]
    zone_upper = p["zone_upper"]

    vm = get_multiplier(instrument_id)
    mr = get_margin_rate(instrument_id)

    # 计算布林带
    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, bb_period, bb_std
    )

    close_vals = df["close"].values
    high_vals = df["high"].values
    dates = df["date"].values

    trades = []
    state_log = []
    open_trade = None  # 当前持仓
    current_margin = 0  # 当前持仓保证金

    # 状态机变量
    state = STATE_IDLE
    h_left = 0.0
    h_left_idx = -1
    search_start = 0  # 30日扫描窗口起点
    entry_bar_count = 0  # LEFT_PEAK_FOUND 后的K线计数（超时退出）

    n = len(df)

    for i in range(bb_period + lookback, n):
        bb_upper = upper[i]
        bb_middle = middle[i]
        bw = bandwidth[i]
        close = close_vals[i]

        if np.isnan(bb_upper) or np.isnan(bb_middle):
            continue

        # ====================================================
        # 持仓中 → 检查止盈
        # ====================================================
        if open_trade is not None:
            if close <= bb_middle:
                open_trade.close(i, dates[i], close)
                current_margin -= open_trade.open_price * vm * mr * open_trade.volume
                trades.append(open_trade)
                state_log.append((i, STATE_IN_POSITION, STATE_IDLE,
                    f"止盈平仓: close={close:.2f} ≤ middle={bb_middle:.2f}"))
                open_trade = None
                state = STATE_IDLE
                h_left = 0.0
                h_left_idx = -1
            continue

        # ====================================================
        # 空仓 → 状态机
        # ====================================================
        if state == STATE_IDLE:
            if bw > bandwidth_min:
                old = state
                state = STATE_WAITING_PULLBACK
                state_log.append((i, old, state,
                    f"带宽达标: bw={bw:.4f} > {bandwidth_min}"))

        # 注意: 用 if 而非 elif，允许同一根K线内完成 IDLE→WAITING_PULLBACK→LEFT_PEAK_FOUND
        if state == STATE_WAITING_PULLBACK:
            if close <= bb_middle:
                # 回溯 lookback 找左峰（包含当前bar，用high）
                search_start = max(0, i - lookback + 1)
                window_highs = high_vals[search_start:i + 1]
                max_offset = int(np.argmax(window_highs))
                h_left = float(window_highs[max_offset])
                h_left_idx = search_start + max_offset

                old = state
                state = STATE_LEFT_PEAK_FOUND
                entry_bar_count = 0  # 重置等待计数
                state_log.append((i, old, state,
                    f"左峰确认: H_left={h_left:.2f}, "
                    f"区间=[{h_left*zone_lower:.2f}, {h_left*zone_upper:.2f}]"))

        elif state == STATE_LEFT_PEAK_FOUND:
            entry_bar_count += 1

            # 超时退出：等待超过回溯窗口仍未进入区间 → 形态失效
            if entry_bar_count > lookback:
                state_log.append((i, STATE_LEFT_PEAK_FOUND, STATE_IDLE,
                    f"形态超时: 等待{entry_bar_count}根K线未进入区间, 重置"))
                state = STATE_IDLE
                h_left = 0.0
                h_left_idx = -1
                entry_bar_count = 0
                continue

            # 价格突破区间上沿 → 形态失效
            if close > h_left * zone_upper:
                old = state
                state = STATE_IDLE
                state_log.append((i, old, state,
                    f"形态失效: close={close:.2f} > {h_left*zone_upper:.2f}"))
                h_left = 0.0
                h_left_idx = -1
                entry_bar_count = 0
                continue

            # 价格进入区间 → 做空
            if h_left * zone_lower <= close <= h_left * zone_upper:
                # 计算手数
                margin_per_lot = close * vm * mr
                if margin_per_lot > 0:
                    max_by_trade = int(MAX_PER_TRADE // margin_per_lot)
                    remaining = MAX_TOTAL_EXPOSURE - current_margin
                    max_by_total = int(remaining // margin_per_lot) if remaining > 0 else 0
                    volume = max(min(max_by_trade, max_by_total), 1)
                else:
                    volume = 0

                if volume > 0:
                    open_trade = Trade(
                        i, dates[i], close, volume,
                        h_left, h_left_idx, search_start, i,
                        h_left * zone_upper, bb_middle,
                        state_trace=list(state_log[-5:])
                    )
                    current_margin += close * vm * mr * volume
                    old = state
                    state = STATE_IN_POSITION
                    state_log.append((i, old, state,
                        f"开空仓: close={close:.2f} ∈ "
                        f"[{h_left*zone_lower:.2f}, {h_left*zone_upper:.2f}], "
                        f"手数={volume}"))

    # 未平仓交易留在 trades 中（标记为未平仓）
    if open_trade is not None:
        trades.append(open_trade)

    indicators = {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
    }
    return trades, indicators, state_log


# ============================================================
# 盈亏计算
# ============================================================
def calc_trade_pnl(trade, volume_multiple, fee_rate, margin_rate):
    """计算单笔交易盈亏明细"""
    points = trade.open_price - trade.close_price
    gross = points * trade.volume * volume_multiple
    fee = (trade.open_price + trade.close_price) * trade.volume * volume_multiple * fee_rate
    net = gross - fee
    margin = trade.open_price * trade.volume * volume_multiple * margin_rate
    return_rate = net / margin * 100 if margin > 0 else 0

    if hasattr(trade.open_date, "strftime"):
        open_dt = pd.Timestamp(trade.open_date)
        close_dt = pd.Timestamp(trade.close_date)
    else:
        open_dt = pd.Timestamp(str(trade.open_date))
        close_dt = pd.Timestamp(str(trade.close_date))
    holding_days = (close_dt - open_dt).days

    return {
        "open_date": trade.open_date,
        "open_price": trade.open_price,
        "close_date": trade.close_date,
        "close_price": trade.close_price,
        "volume": trade.volume,
        "h_left": trade.h_left,
        "holding_days": holding_days,
        "margin": round(margin, 2),
        "points": round(points, 2),
        "fee": round(fee, 2),
        "net_pnl": round(net, 2),
        "return_rate": round(return_rate, 2),
        "win": net > 0,
    }


# ============================================================
# 过程图生成
# ============================================================
def plot_trade_process(records, trade_details, trades_raw, instrument, output_path, params):
    """绘制交易过程图：OHLC + 布林带 + 左右峰标记 + 开平仓点"""
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, params["bb_period"], params["bb_std"]
    )
    df["bb_upper"] = upper
    df["bb_middle"] = middle
    df["bb_lower"] = lower
    df["bandwidth"] = bandwidth

    # 匹配交易到 DataFrame 行索引
    trade_info = []
    for td, tr in zip(trade_details, trades_raw):
        open_date = pd.Timestamp(td["open_date"])
        close_date = pd.Timestamp(td["close_date"])
        open_matches = df.index[df["date"] == open_date]
        close_matches = df.index[df["date"] == close_date]
        if len(open_matches) > 0 and len(close_matches) > 0:
            trade_info.append((open_matches[0], close_matches[0], td, tr))
    if not trade_info:
        return

    # 截取交易区域
    earliest_open = min(oi for oi, ci, td, tr in trade_info)
    latest_close = max(ci for oi, ci, td, tr in trade_info)
    margin = max(20, params["left_peak_lookback"] + 10)
    start_idx = max(0, earliest_open - margin)
    end_idx = min(len(df) - 1, latest_close + 10)

    df_slice = df.iloc[start_idx:end_idx + 1].copy().reset_index(drop=True)
    n = len(df_slice)
    x = np.arange(n)

    fig_w = max(14, min(28, n * 0.3))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(fig_w, 12),
                                    gridspec_kw={"height_ratios": [3, 1]})

    # --- OHLC ---
    bar_width = 0.6
    for i in range(n):
        o, h, l, c = [float(df_slice[col].iloc[i]) for col in ["open", "high", "low", "close"]]
        up = c >= o
        color = "#D32F2F" if up else "#388E3C"
        ax1.plot([i, i], [l, h], color=color, linewidth=0.5, zorder=1)
        body_bottom = min(o, c)
        body_height = abs(c - o) or max((h - l) * 0.01, 0.001)
        rect = Rectangle((i - bar_width / 2, body_bottom), bar_width, body_height,
                          facecolor=color, edgecolor=color, alpha=0.85, zorder=2)
        ax1.add_patch(rect)

    # --- 布林带 ---
    ax1.plot(x, df_slice["bb_upper"].values, "r--", linewidth=0.8, alpha=0.7, label="上轨")
    ax1.plot(x, df_slice["bb_middle"].values, "b-", linewidth=1.2, alpha=0.8, label="中轨")
    ax1.plot(x, df_slice["bb_lower"].values, "g--", linewidth=0.8, alpha=0.7, label="下轨")

    # --- 日期刻度 ---
    date_labels = [d.strftime("%Y-%m-%d") for d in df_slice["date"]]
    tick_step = max(1, n // 15)
    ax1.set_xticks(x[::tick_step])
    ax1.set_xticklabels(date_labels[::tick_step], rotation=45, ha="right", fontsize=7)

    # --- 交易标记 ---
    colors_pnl = plt.cm.tab10(np.linspace(0, 1, max(len(trade_info), 1)))
    for j, (open_idx, close_idx, td, tr) in enumerate(trade_info):
        sx = open_idx - start_idx
        cx = close_idx - start_idx
        open_price = td["open_price"]
        close_price = td["close_price"]
        h_left = tr.h_left
        h_left_idx_abs = getattr(tr, "h_left_idx", -1)
        scan_start_abs = getattr(tr, "scan_start_idx", -1)
        scan_end_abs = getattr(tr, "scan_end_idx", -1)

        # ---- 30日扫描窗口：半透明背景色块 ----
        # scan_start_abs = 30日前（窗口左边界）
        # scan_end_abs = 回踩中轨的K线（扫描起点，从此向前回溯30日找左峰）
        if scan_start_abs >= 0 and scan_end_abs >= 0:
            win_start = scan_start_abs - start_idx
            win_end = scan_end_abs - start_idx
            # 裁剪到可见范围
            win_start_clipped = max(0, win_start)
            win_end_clipped = min(n - 1, win_end)
            if win_end_clipped > win_start_clipped:
                ax1.axvspan(win_start_clipped - 0.5, win_end_clipped + 0.5,
                            alpha=0.10, color="orange", zorder=0)
                # 窗口左边界竖线（30日前）
                ax1.axvline(x=win_start_clipped, color="orange", linewidth=1.0,
                            linestyle="--", alpha=0.5, zorder=3)
                # 窗口右边界竖线（回踩中轨 = 扫描起点，加粗加亮）
                ax1.axvline(x=win_end_clipped, color="darkorange", linewidth=2.0,
                            linestyle="-", alpha=0.8, zorder=3)

                # 扫描起点标注：回踩中轨的K线（窗口右侧）
                scan_start_date = df_slice["date"].iloc[win_end_clipped].strftime("%Y-%m-%d")
                bb_mid_val = float(df_slice["bb_middle"].iloc[win_end_clipped])
                ax1.annotate(f">> 回踩中轨\n   扫描起点\n   {scan_start_date}\n   中轨={bb_mid_val:,.0f}",
                            (win_end_clipped, bb_mid_val),
                            textcoords="offset points", xytext=(15, -10), fontsize=8,
                            fontweight="bold", color="darkorange", ha="left",
                            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow",
                                      edgecolor="darkorange", alpha=0.9))

                # 30日前位置标注（窗口左侧）
                earliest_date = df_slice["date"].iloc[win_start_clipped].strftime("%m-%d")
                ax1.annotate(f"回溯{params['left_peak_lookback']}日\n{earliest_date}",
                            (win_start_clipped, df_slice["high"].iloc[win_start_clipped]),
                            textcoords="offset points", xytext=(-10, 15), fontsize=7,
                            color="gray", ha="right",
                            arrowprops=dict(arrowstyle="->", color="gray", lw=0.5))

                # 窗口顶部标注（从右到左的箭头表示回溯方向）
                mid_win = (win_start_clipped + win_end_clipped) / 2
                y_top = float(df_slice["high"].max()) * 1.02
                ax1.annotate(f"回溯 {params['left_peak_lookback']} 日找左峰 <<<",
                            (win_end_clipped, y_top), fontsize=9,
                            color="darkorange", ha="right", va="top",
                            bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow",
                                      edgecolor="orange", alpha=0.85))

        # ---- 左峰标记：在H_left所在的K线上画星标 ----
        if h_left_idx_abs >= 0:
            peak_x = h_left_idx_abs - start_idx
            if 0 <= peak_x < n:
                peak_date = df_slice["date"].iloc[peak_x].strftime("%Y-%m-%d")
                peak_high = float(df_slice["high"].iloc[peak_x])
                # 大星标
                ax1.scatter(peak_x, h_left, marker="*", color="darkorange", s=350,
                            zorder=10, edgecolors="brown", linewidths=1.5,
                            label="H_left(左峰)" if j == 0 else "")
                # 标注
                ax1.annotate(f"H_left\n{h_left:,.0f}\n{peak_date}",
                            (peak_x, h_left),
                            textcoords="offset points", xytext=(0, 25), fontsize=9,
                            fontweight="bold", color="darkorange", ha="center",
                            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                                      edgecolor="darkorange", alpha=0.9),
                            arrowprops=dict(arrowstyle="->", color="darkorange", lw=1.0))

        # 左峰水平线和入场区间
        if h_left > 0:
            zone_l = h_left * params["zone_lower"]
            zone_u = h_left * params["zone_upper"]
            # 左峰水平虚线（从扫描窗口起点延伸到开仓点之后）
            left_edge = max(0, sx - params["left_peak_lookback"])
            ax1.hlines(h_left, left_edge, sx + 2, colors="orange", linewidth=1.5,
                       linestyles="--", alpha=0.6)
            # 入场区间上下沿
            ax1.hlines(zone_l, left_edge, sx + 2, colors="brown", linewidth=0.7,
                       linestyles=":", alpha=0.5)
            ax1.hlines(zone_u, left_edge, sx + 2, colors="brown", linewidth=0.7,
                       linestyles=":", alpha=0.5)
            # 区间标注
            ax1.annotate(f"入场 [{zone_l:,.0f}, {zone_u:,.0f}]",
                        (sx, zone_l), textcoords="offset points", xytext=(5, -15),
                        fontsize=7, color="brown", alpha=0.8)

        # 开仓点
        ax1.scatter(sx, open_price, marker="v", color="red", s=180, zorder=5,
                    edgecolors="darkred", linewidths=1.5)
        ax1.annotate(f"空 {j+1}\n{open_price:,.0f}", (sx, open_price),
                     textcoords="offset points", xytext=(10, -35), fontsize=8,
                     color="darkred",
                     arrowprops=dict(arrowstyle="->", color="darkred", lw=0.8))

        # 平仓点
        ax1.scatter(cx, close_price, marker="^", color="limegreen", s=180, zorder=5,
                    edgecolors="darkgreen", linewidths=1.5)
        ax1.annotate(f"平 {j+1}\n{close_price:,.0f}", (cx, close_price),
                     textcoords="offset points", xytext=(10, 25), fontsize=8,
                     color="darkgreen",
                     arrowprops=dict(arrowstyle="->", color="darkgreen", lw=0.8))

        # 开仓→平仓连线
        ax1.plot([sx, cx], [open_price, close_price], "k--", linewidth=1, alpha=0.4, zorder=3)

        # 持仓区间着色
        ax1.axvspan(sx - 0.5, cx + 0.5, alpha=0.06, color="red" if td["net_pnl"] > 0 else "blue")

        # 盈亏标注
        pnl = td["net_pnl"]
        mid_x = (sx + cx) / 2
        mid_price = (open_price + close_price) / 2
        pnl_color = "darkgreen" if pnl > 0 else "darkred"
        ax1.annotate(f"{'盈' if pnl > 0 else '亏'} {pnl:+,.0f}\n"
                     f"持{td['holding_days']}天 {td['return_rate']:+.1f}%",
                     (mid_x, mid_price), fontsize=9, fontweight="bold",
                     ha="center", va="bottom" if pnl > 0 else "top", color=pnl_color,
                     bbox=dict(boxstyle="round,pad=0.4", facecolor="yellow", alpha=0.75))

    legend_elements = [
        Line2D([0], [0], color="r", linestyle="--", label="上轨"),
        Line2D([0], [0], color="b", linestyle="-", label="中轨"),
        Line2D([0], [0], color="g", linestyle="--", label="下轨"),
        Line2D([0], [0], color="darkorange", linestyle="--", linewidth=1.2,
               label=f"{params['left_peak_lookback']}日扫描窗口", alpha=0.6),
        Line2D([0], [0], marker="*", color="darkorange", linestyle="None",
               label="H_left(左峰)", markersize=12, markeredgecolor="brown"),
        Line2D([0], [0], color="brown", linestyle=":", label="入场区间"),
        Line2D([0], [0], marker="v", color="red", linestyle="None", label="开空仓", markersize=8),
        Line2D([0], [0], marker="^", color="limegreen", linestyle="None", label="平空仓", markersize=8),
    ]
    ax1.legend(handles=legend_elements, loc="upper left", fontsize=8)
    ax1.set_title(f"{instrument} 双峰做空策略 · 交易过程", fontsize=14, fontweight="bold")
    ax1.set_ylabel("价格")
    ax1.set_xlim(-1, n)
    ax1.grid(True, alpha=0.3)

    # --- 下图：累计收益曲线 ---
    pnls = [td["net_pnl"] for _, _, td, _ in trade_info]
    close_positions = [ci - start_idx for _, ci, _, _ in trade_info]
    cumulative = np.cumsum(pnls)

    ax2.step(close_positions, cumulative, where="post", color="royalblue", linewidth=1.8)
    ax2.fill_between(close_positions, cumulative, 0, step="post",
                     where=[c >= 0 for c in cumulative], alpha=0.3, color="green")
    ax2.fill_between(close_positions, cumulative, 0, step="post",
                     where=[c < 0 for c in cumulative], alpha=0.3, color="red")
    ax2.axhline(y=0, color="gray", linewidth=0.5)
    ax2.set_title(f"累计收益  总盈亏: {sum(pnls):>+,.0f}  胜率: {sum(1 for p in pnls if p > 0)}/{len(pnls)}", fontsize=12)
    ax2.set_ylabel("盈亏金额 (元)")
    ax2.set_xlim(-1, n)
    ax2.set_xticks(x[::tick_step])
    ax2.set_xticklabels(date_labels[::tick_step], rotation=45, ha="right", fontsize=7)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表已保存: {output_path}")


# ============================================================
# 回测运行（单品种）
# ============================================================
def backtest_one(filepath, params):
    """回测单个数据文件，返回结果字典"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    records = raw.get("data", [])
    if len(records) < params["bb_period"] + params["left_peak_lookback"] + 5:
        return None

    instrument = raw.get("instrument", os.path.basename(filepath).replace("_kline.json", ""))
    exchange = raw.get("exchange", "?")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    vm = get_multiplier(instrument)
    mr = get_margin_rate(instrument)

    trades_raw, indicators, state_log = run_single_backtest(df, params, instrument)

    # 只保留已平仓的交易
    closed_trades = [t for t in trades_raw if t.close_idx is not None]
    open_trades_count = len(trades_raw) - len(closed_trades)

    trade_details = [calc_trade_pnl(t, vm, params["fee_rate"], mr) for t in closed_trades]

    # 带宽统计
    bw = indicators["bandwidth"]
    valid_bw = bw[~np.isnan(bw)]
    max_bw = float(np.nanmax(bw)) if len(valid_bw) > 0 else 0
    bw_above = float(np.mean(bw > params["bandwidth_min"]) * 100)

    result = {
        "instrument": instrument,
        "exchange": exchange,
        "records": len(df),
        "date_start": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "date_end": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "max_bandwidth": round(max_bw, 4),
        "bw_above_pct": round(bw_above, 1),
        "volume_multiple": vm,
        "margin_rate": mr,
        "trade_count": len(trade_details),
        "open_trades": open_trades_count,
        "state_log": state_log,
        "trades": trade_details,
        "trades_raw": closed_trades,
        "records_raw": records,
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
        result["avg_return_rate"] = round(
            sum(t["return_rate"] for t in trade_details) / len(trade_details), 2
        )

        # 累计收益与最大回撤
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = cumulative - peak
        result["max_drawdown"] = round(float(drawdown.min()), 2)

        # 总保证金
        result["total_margin"] = round(sum(t["margin"] for t in trade_details), 2)

    return result


def backtest_all(data_dir, params):
    """批量回测所有品种"""
    all_results = []
    files = sorted(os.listdir(data_dir))

    for fname in files:
        if not fname.endswith("_kline.json"):
            continue
        filepath = os.path.join(data_dir, fname)
        try:
            result = backtest_one(filepath, params)
            if result is not None:
                all_results.append(result)
                trades_str = f"{result['trade_count']}笔" if result['trade_count'] > 0 else "无信号"
                pnl_str = f"盈亏 {result.get('total_pnl', 0):>+,.0f}" if result['trade_count'] > 0 else ""
                print(f"  {result['instrument']:12s}  {trades_str:8s}  {pnl_str}")
        except Exception as e:
            print(f"  [错误] {fname}: {e}")

    return all_results


# ============================================================
# 报告生成
# ============================================================
def build_report(all_results, params):
    """生成 Markdown 回测报告"""
    lines = []
    lines.append("# 双峰做空策略 · 回测报告")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 策略: 日线双峰左侧交易做空")
    lines.append("")

    # 参数
    lines.append("## 一、策略参数")
    lines.append("")
    lines.append("| 参数 | 取值 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| bb_period | {params['bb_period']} | 布林带周期 |")
    lines.append(f"| bb_std | {params['bb_std']} | 标准差倍数 |")
    lines.append(f"| bandwidth_min | {params['bandwidth_min']} | 最小带宽（中轨的{params['bandwidth_min']*100:.0f}%） |")
    lines.append(f"| left_peak_lookback | {params['left_peak_lookback']} | 左峰回溯窗口 |")
    lines.append(f"| zone_lower | {params['zone_lower']} | 入场区间下沿（×H_left） |")
    lines.append(f"| zone_upper | {params['zone_upper']} | 入场区间上沿（×H_left） |")
    lines.append(f"| fee_rate | {params['fee_rate']} | 手续费率（单边） |")
    lines.append("")
    lines.append("### 策略规则")
    lines.append("1. 布林带带宽 > 15% → 进入监控")
    lines.append("2. 收盘价 ≤ 布林中轨 → 回溯30日找左峰 H_left")
    lines.append("3. 价格进入 [0.99×H_left, 1.02×H_left] → 左侧交易立即做空")
    lines.append("4. 价格触及布林中轨 → 止盈平仓")
    lines.append("5. 价格突破 1.02×H_left → 形态失效，放弃本轮")
    lines.append("6. 不设止损（注意风险）")
    lines.append("")

    # 资金管理
    lines.append("### 资金管理")
    lines.append("| 规则 | 数值 |")
    lines.append("|------|------|")
    lines.append("| 总保证金 | 1000 万 |")
    lines.append("| 单笔保证金上限 | 100 万 |")
    lines.append("| 同时持仓保证金上限 | 600 万 |")
    lines.append("")

    # 汇总表
    lines.append("## 二、回测汇总")
    lines.append("")
    total_trades = sum(r["trade_count"] for r in all_results)
    total_pnl = sum(r.get("total_pnl", 0) for r in all_results)
    total_wins = sum(r.get("win_count", 0) for r in all_results)
    total_losses = sum(r.get("loss_count", 0) for r in all_results)
    total_margin_all = sum(r.get("total_margin", 0) for r in all_results)
    instruments_with_trades = sum(1 for r in all_results if r["trade_count"] > 0)

    lines.append(f"- 测试品种数: {len(all_results)}")
    lines.append(f"- 有交易品种数: {instruments_with_trades}")
    lines.append(f"- 总交易笔数: {total_trades}")
    lines.append(f"- 总盈亏: **{total_pnl:>+,.0f}** 元")
    lines.append(f"- 总保证金: {total_margin_all:>+,.0f} 元")
    if total_margin_all > 0:
        lines.append(f"- 总收益率: {total_pnl/total_margin_all*100:+.2f}%")
    if total_trades > 0:
        lines.append(f"- 整体胜率: {total_wins}/{total_trades} = {total_wins/total_trades*100:.1f}%")
    lines.append("")

    # 品种明细表
    lines.append("## 三、品种明细")
    lines.append("")
    header = ("| 品种 | 交易所 | 数据范围 | 记录数 | 最大带宽 | bw>阈值 | "
              "交易笔数 | 盈利 | 亏损 | 胜率 | 总盈亏 | 最大回撤 | 平均持仓 |")
    lines.append(header)
    lines.append("|" + "|".join(["------"] * 12) + "|")

    for r in sorted(all_results, key=lambda x: x.get("total_pnl", float("-inf")), reverse=True):
        inst = r["instrument"]
        ex = r["exchange"]
        dr = f"{r['date_start']}~{r['date_end']}"
        n = r["records"]
        mbw = f"{r['max_bandwidth']:.3f}"
        bap = f"{r['bw_above_pct']:.0f}%"
        tc = r["trade_count"]

        if tc > 0:
            wc = r.get("win_count", 0)
            lc = r.get("loss_count", 0)
            wr = f"{r.get('win_rate', 0):.0f}%"
            tp = f"{r.get('total_pnl', 0):>+,.0f}"
            md = f"{r.get('max_drawdown', 0):>+,.0f}"
            ah = f"{r.get('avg_holding_days', 0):.0f}d"
        else:
            wc, lc, wr, tp, md, ah = "-", "-", "-", "-", "-", "-"

        lines.append(f"| {inst} | {ex} | {dr} | {n} | {mbw} | {bap} | "
                     f"{tc} | {wc} | {lc} | {wr} | {tp} | {md} | {ah} |")
    lines.append("")

    # 交易详情
    lines.append("## 四、交易明细")
    lines.append("")

    for r in sorted(all_results, key=lambda x: x.get("total_pnl", float("-inf")), reverse=True):
        if r["trade_count"] == 0:
            continue
        inst = r["instrument"]
        lines.append(f"### {inst}")
        lines.append("")
        lines.append(f"- 数据: {r['date_start']} ~ {r['date_end']} ({r['records']}条)")
        lines.append(f"- 合约乘数: {r['volume_multiple']}, 保证金率: {r['margin_rate']*100:.0f}%")
        lines.append(f"- 最大带宽: {r['max_bandwidth']:.4f}, 带宽>阈值比例: {r['bw_above_pct']:.0f}%")
        if r["trade_count"] > 0:
            lines.append(f"- 总盈亏: {r.get('total_pnl', 0):>+,.0f}元, "
                         f"胜率: {r.get('win_rate', '-')}%, "
                         f"最大回撤: {r.get('max_drawdown', 0):>+,.0f}元, "
                         f"平均持仓: {r.get('avg_holding_days', '-')}天")
        lines.append("")

        if r["trades"]:
            lines.append("| # | 开仓日期 | 开仓价 | 平仓日期 | 平仓价 | 手数 | H_left | 持仓天 | 保证金 | 点数 | 净盈亏 | 收益率 |")
            lines.append("|---|---------|--------|---------|--------|------|--------|--------|--------|------|--------|--------|")
            for j, t in enumerate(r["trades"], 1):
                od = str(t["open_date"])[:10]
                cd = str(t["close_date"])[:10]
                hl = f"{t.get('h_left', 0):,.0f}"
                lines.append(
                    f"| {j} | {od} | {t['open_price']:,.0f} | {cd} | {t['close_price']:,.0f} | "
                    f"{t['volume']} | {hl} | {t['holding_days']} | {t['margin']:>+,.0f} | "
                    f"{t['points']:>+,.1f} | {t['net_pnl']:>+,.0f} | {t['return_rate']:>+.1f}% |"
                )
            lines.append("")

    # 结论
    lines.append("## 五、结论与分析")
    lines.append("")

    # 统计
    traded = [r for r in all_results if r["trade_count"] > 0]
    if traded:
        pnls_all = []
        for r in traded:
            pnls_all.extend([t["net_pnl"] for t in r["trades"]])
        pnls_all = np.array(pnls_all)

        lines.append(f"### 整体统计")
        lines.append(f"- 测试品种: {len(all_results)} 个")
        lines.append(f"- 有交易品种: {len(traded)} 个")
        lines.append(f"- 总交易: {len(pnls_all)} 笔")
        lines.append(f"- 总盈亏: **{pnls_all.sum():>+,.0f}** 元")
        lines.append(f"- 平均盈亏: {pnls_all.mean():>+,.0f} 元/笔")
        lines.append(f"- 最大单笔盈利: {pnls_all.max():>+,.0f} 元")
        lines.append(f"- 最大单笔亏损: {pnls_all.min():>+,.0f} 元")
        lines.append(f"- 盈利笔数: {sum(pnls_all > 0)}, 亏损笔数: {sum(pnls_all < 0)}")
        lines.append(f"- 胜率: {sum(pnls_all > 0)/len(pnls_all)*100:.1f}%")
        lines.append(f"- 盈亏比: {abs(pnls_all[pnls_all > 0].mean() / pnls_all[pnls_all < 0].mean()):.2f}"
                     if sum(pnls_all < 0) > 0 and sum(pnls_all > 0) > 0 else "-")

        # 最优品种
        best = max(traded, key=lambda r: r.get("total_pnl", float("-inf")))
        worst = min(traded, key=lambda r: r.get("total_pnl", float("inf")))
        lines.append(f"- 最盈利品种: **{best['instrument']}** ({best.get('total_pnl', 0):>+,.0f}元, "
                     f"{best['trade_count']}笔, 胜率{best.get('win_rate', '-')}%)")
        lines.append(f"- 最大亏损品种: **{worst['instrument']}** ({worst.get('total_pnl', 0):>+,.0f}元, "
                     f"{worst['trade_count']}笔)")

        # 按胜率
        best_wr = max(traded, key=lambda r: r.get("win_rate", 0))
        lines.append(f"- 最高胜率品种: **{best_wr['instrument']}** ({best_wr.get('win_rate', 0)}%)")
        lines.append("")

        lines.append("### 策略特征")
        avg_holding = np.mean([r.get("avg_holding_days", 0) for r in traded if r.get("avg_holding_days")])
        lines.append(f"- 策略类型: 日线左侧交易（双峰做空）")
        lines.append(f"- 平均持仓天数: {avg_holding:.0f} 天")
        lines.append(f"- 入场方式: 价格触及左峰区间立即做空，不等确认信号")
        lines.append(f"- 止盈方式: 价格回到布林中轨全仓平仓")
        lines.append(f"- 特点: 不设止损，依赖形态失效条件（突破1.02×H_left）控制风险")
        lines.append(f"- 潜在风险: 震荡行情中可能在左峰区间反复触发入场，需要关注信号过滤效果")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="双峰做空策略 — 独立回测脚本"
    )
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help=f"D1数据目录 (默认: {DEFAULT_DATA_DIR})")
    parser.add_argument("--instrument", default=None,
                        help="指定品种代码 (如 rb2605)，不指定则回测全部")
    parser.add_argument("--bandwidth-min", type=float, default=0.15,
                        help="最小带宽阈值 (默认: 0.15)")
    parser.add_argument("--zone-lower", type=float, default=0.99,
                        help="入场区间下沿 (默认: 0.99)")
    parser.add_argument("--zone-upper", type=float, default=1.02,
                        help="入场区间上沿 (默认: 1.02)")
    parser.add_argument("--lookback", type=int, default=30,
                        help="左峰回溯窗口 (默认: 30)")
    parser.add_argument("--no-chart", action="store_true",
                        help="跳过图表生成")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,
                        help=f"输出目录 (默认: {OUTPUT_DIR})")
    args = parser.parse_args()

    params = {**DEFAULT_PARAMS}
    params["bandwidth_min"] = args.bandwidth_min
    params["zone_lower"] = args.zone_lower
    params["zone_upper"] = args.zone_upper
    params["left_peak_lookback"] = args.lookback

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 60)
    print("双峰做空策略 · 回测")
    print("=" * 60)
    print(f"参数: BB({params['bb_period']},{params['bb_std']}), "
          f"带宽>{params['bandwidth_min']}, "
          f"左峰回溯={params['left_peak_lookback']}, "
          f"入场区间=[{params['zone_lower']},{params['zone_upper']}]×H_left")
    print(f"数据目录: {args.data_dir}")
    print()

    if args.instrument:
        # 单品种回测
        fname = f"{args.instrument}_kline.json"
        filepath = os.path.join(args.data_dir, fname)
        if not os.path.exists(filepath):
            # 尝试大小写
            for f in os.listdir(args.data_dir):
                if args.instrument.lower() in f.lower():
                    filepath = os.path.join(args.data_dir, f)
                    break
            else:
                print(f"错误: 找不到 {args.instrument} 的数据文件")
                sys.exit(1)

        print(f"回测品种: {args.instrument}")
        result = backtest_one(filepath, params)
        if result is None:
            print("数据不足，无法回测")
            sys.exit(1)

        all_results = [result]
    else:
        # 批量回测
        print("回测品种: 全部")
        print("-" * 40)
        all_results = backtest_all(args.data_dir, params)

    print()

    # 生成报告
    print("生成回测报告...")
    report = build_report(all_results, params)

    report_filename = f"backtest_double_top_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(args.output_dir, report_filename)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告已保存: {report_path}")

    # 生成过程图
    if not args.no_chart:
        print("\n生成过程图...")
        for r in all_results:
            if r["trade_count"] == 0:
                continue
            inst = r["instrument"]
            chart_filename = f"backtest_double_top_{inst}.png"
            chart_path = os.path.join(args.output_dir, chart_filename)
            try:
                plot_trade_process(
                    r["records_raw"],
                    r["trades"],
                    r["trades_raw"],
                    inst,
                    chart_path,
                    params
                )
            except Exception as e:
                print(f"  [警告] {inst} 图表生成失败: {e}")

    # 控制台输出摘要
    print("\n" + "=" * 60)
    print("回测结果摘要")
    print("=" * 60)

    total_trades = sum(r["trade_count"] for r in all_results)
    total_pnl = sum(r.get("total_pnl", 0) for r in all_results)
    total_wins = sum(r.get("win_count", 0) for r in all_results)
    total_losses = sum(r.get("loss_count", 0) for r in all_results)

    print(f"{'品种':<12s} {'交易':>5s} {'盈利':>6s} {'亏损':>6s} {'胜率':>6s} {'总盈亏':>12s} {'最大回撤':>12s}")
    print("-" * 60)
    for r in sorted(all_results, key=lambda x: x.get("total_pnl", float("-inf")), reverse=True):
        if r["trade_count"] > 0:
            print(f"{r['instrument']:<12s} {r['trade_count']:>5d} "
                  f"{r.get('win_count', 0):>6d} {r.get('loss_count', 0):>6d} "
                  f"{r.get('win_rate', 0):>5.0f}% "
                  f"{r.get('total_pnl', 0):>+12,.0f} {r.get('max_drawdown', 0):>+12,.0f}")

    print("-" * 60)
    print(f"{'合计':<12s} {total_trades:>5d} {total_wins:>6d} {total_losses:>6d} "
          f"{total_wins/total_trades*100 if total_trades > 0 else 0:>5.0f}% "
          f"{total_pnl:>+12,.0f}")
    print()

    if all_results:
        instruments_with_trades = [r for r in all_results if r["trade_count"] > 0]
        print(f"有交易的品种: {len(instruments_with_trades)}/{len(all_results)}")
        if instruments_with_trades:
            best = max(instruments_with_trades, key=lambda r: r.get("total_pnl", float("-inf")))
            worst = min(instruments_with_trades, key=lambda r: r.get("total_pnl", float("inf")))
            print(f"最盈利: {best['instrument']} ({best.get('total_pnl', 0):>+,.0f}元)")
            print(f"最大亏损: {worst['instrument']} ({worst.get('total_pnl', 0):>+,.0f}元)")

    print(f"\n报告: {report_path}")
    print("完成！")


if __name__ == "__main__":
    main()
