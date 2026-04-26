# -*- coding: utf-8 -*-
"""
布林带做空策略 - 可视化脚本
对31个品种绘制K线+布林带+交易标注图
"""

import json
import os
import sys
import glob

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 合约乘数表
MULTIPLIERS = {
    "ag": 15, "au": 1000, "cu": 5, "al": 5, "zn": 5, "ni": 1,
    "bu": 10, "rb": 10, "hc": 10, "i": 100, "ru": 10,
    "FG": 20, "SA": 20, "TA": 5, "MA": 10, "RM": 10, "SR": 10,
    "CF": 5, "c": 10, "cs": 10, "m": 10, "a": 10, "p": 10, "y": 10,
    "IF": 300, "IC": 200, "IH": 300, "IM": 200,
    "T": 10000, "TF": 10000, "TS": 20000,
}

DATA_DIR = r"C:\Users\Administrator\Desktop\quanda_exports"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_data(filepath: str) -> pd.DataFrame:
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    records = raw.get("data", [])
    if not records:
        return None
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["instrument"] = raw.get("instrument", os.path.basename(filepath).replace("_kline.json", ""))
    df["exchange"] = raw.get("exchange", "?")
    df["kline_style"] = raw.get("kline_style", "?")
    return df


def calc_bbands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    close = pd.Series(df["close"].values.astype(float))
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    df["bb_upper"] = upper.values
    df["bb_middle"] = middle.values
    df["bb_lower"] = lower.values
    df["bandwidth"] = np.where(middle.values > 0, (upper.values - lower.values) / middle.values, 0)
    return df


class Trade:
    def __init__(self, open_date, open_price, volume):
        self.open_date = open_date
        self.open_price = open_price
        self.volume = volume
        self.close_date = None
        self.close_price = None
        self.closed = False

    def close(self, close_date, close_price):
        self.close_date = close_date
        self.close_price = close_price
        self.closed = True


def run_backtest(df: pd.DataFrame, params: dict) -> list:
    trades = []
    open_trade = None
    monitoring = False
    continuous_count = 0
    bb_period = params["bb_period"]

    for i in range(bb_period, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        bb_upper = row["bb_upper"]
        bb_middle = row["bb_middle"]
        bb_lower = row["bb_lower"]
        bandwidth = row["bandwidth"]
        pre_bb_upper = prev["bb_upper"]
        pre_bb_lower = prev["bb_lower"]

        upper_rising = bb_upper > pre_bb_upper
        lower_rising = bb_lower > pre_bb_lower
        bandwidth_ok = bandwidth > params["bandwidth_threshold"]
        preconditions_met = upper_rising and lower_rising and bandwidth_ok

        if preconditions_met:
            monitoring = True
            if row["close"] > row["open"]:
                continuous_count += 1
            else:
                continuous_count = 0
        else:
            monitoring = False
            continuous_count = 0

        if open_trade is not None and row["close"] <= bb_middle:
            open_trade.close(row["date"], row["close"])
            trades.append(open_trade)
            open_trade = None

        if open_trade is None and monitoring and continuous_count >= params["continuous_klines"]:
            breakout_price = bb_upper * (1 + params["breakout_threshold"])
            if row["close"] > breakout_price:
                open_trade = Trade(row["date"], row["close"], params["order_volume"])
                monitoring = False
                continuous_count = 0

    return trades


def plot_instrument(df, strict_trades, loose_trades, instrument_name, filepath):
    """绘制单品种K线+布林带+交易标注图"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 10),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=True)

    dates = df["date"]

    # === 上半部分：K线 + 布林带 ===
    ax1.plot(dates, df["close"], color="black", linewidth=0.8, label="收盘价")
    ax1.plot(dates, df["bb_upper"], "r--", linewidth=0.6, alpha=0.7, label="上轨")
    ax1.plot(dates, df["bb_middle"], "b--", linewidth=0.6, alpha=0.7, label="中轨")
    ax1.plot(dates, df["bb_lower"], "g--", linewidth=0.6, alpha=0.7, label="下轨")

    # 填充布林带区域
    ax1.fill_between(dates, df["bb_upper"], df["bb_lower"], alpha=0.05, color="gray")

    # 标注严格参数交易区间
    for t in strict_trades:
        ax1.axvspan(t.open_date, t.close_date, alpha=0.15, color="red", label="_strict_zone" if t == strict_trades[0] else "")
        ax1.scatter(t.open_date, t.open_price, marker="v", color="red", s=150, zorder=5, edgecolors="darkred", linewidths=1.5)
        if t.close_date is not None:
            ax1.scatter(t.close_date, t.close_price, marker="^", color="limegreen", s=150, zorder=5, edgecolors="darkgreen", linewidths=1.5)
            ax1.annotate(f"开空 {t.open_price:.0f}\n平仓 {t.close_price:.0f}",
                        xy=(t.open_date, t.open_price),
                        xytext=(15, 20), textcoords="offset points",
                        fontsize=7, color="red",
                        arrowprops=dict(arrowstyle="->", color="red", lw=0.5))

    # 标注宽松参数交易区间
    for t in loose_trades:
        ax1.axvspan(t.open_date, t.close_date if t.close_date else dates.iloc[-1], alpha=0.10, color="orange", label="_loose_zone" if t == loose_trades[0] else "")
        ax1.scatter(t.open_date, t.open_price, marker="v", color="orange", s=100, zorder=4, edgecolors="darkorange", linewidths=1)
        if t.close_date is not None:
            ax1.scatter(t.close_date, t.close_price, marker="^", color="dodgerblue", s=100, zorder=4, edgecolors="navy", linewidths=1)

    # 图例
    legend_elements = [
        plt.Line2D([0], [0], color="black", linewidth=1, label="收盘价"),
        plt.Line2D([0], [0], color="red", linewidth=1, linestyle="--", label="上轨"),
        plt.Line2D([0], [0], color="blue", linewidth=1, linestyle="--", label="中轨"),
        plt.Line2D([0], [0], color="green", linewidth=1, linestyle="--", label="下轨"),
        plt.Line2D([0], [0], marker="v", color="red", linestyle="", markersize=10, label="严格-开空"),
        plt.Line2D([0], [0], marker="^", color="limegreen", linestyle="", markersize=10, label="严格-平仓"),
        plt.Line2D([0], [0], marker="v", color="orange", linestyle="", markersize=8, label="宽松-开空"),
        plt.Line2D([0], [0], marker="^", color="dodgerblue", linestyle="", markersize=8, label="宽松-平仓"),
    ]
    ax1.legend(handles=legend_elements, loc="upper left", fontsize=8, ncol=2)
    ax1.set_ylabel("价格", fontsize=10)
    ax1.grid(True, alpha=0.3)

    # === 下半部分：带宽曲线 ===
    ax2.plot(dates, df["bandwidth"] * 100, color="purple", linewidth=0.8, label="带宽(%)")
    ax2.axhline(y=25, color="red", linewidth=0.8, linestyle="--", alpha=0.7, label="严格阈值 25%")
    ax2.axhline(y=10, color="orange", linewidth=0.8, linestyle="--", alpha=0.7, label="宽松阈值 10%")
    ax2.fill_between(dates, 25, df["bandwidth"] * 100, where=df["bandwidth"] * 100 >= 25, alpha=0.2, color="red")
    ax2.set_ylabel("带宽 (%)", fontsize=10)
    ax2.set_xlabel("日期", fontsize=10)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.3)

    # 标题
    strict_count = len(strict_trades)
    loose_count = len(loose_trades)
    ax1.set_title(
        f"{instrument_name}  布林带做空策略可视化\n"
        f"严格参数(bw=0.25, bo=0.02, consec=3): {strict_count}笔交易 | "
        f"宽松参数(bw=0.10, bo=0.0, consec=1): {loose_count}笔交易",
        fontsize=12, fontweight="bold"
    )

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=30)

    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, f"{instrument_name}_boll.png")
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  已保存: {output_path}")
    return output_path


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    strict_params = {"bb_period": 20, "bb_std": 2.0, "order_volume": 10,
                     "bandwidth_threshold": 0.25, "breakout_threshold": 0.02,
                     "continuous_klines": 3, "volume_multiple": 10, "fee_rate": 0.0001}

    loose_params = {**strict_params, "bandwidth_threshold": 0.10,
                    "breakout_threshold": 0.0, "continuous_klines": 1}

    files = sorted(glob.glob(os.path.join(DATA_DIR, "*_kline.json")))
    if not files:
        print(f"数据目录中没有文件: {DATA_DIR}")
        return

    print(f"找到 {len(files)} 个品种数据文件\n")

    summary = []

    for filepath in files:
        df = load_data(filepath)
        if df is None:
            continue

        instrument = df["instrument"].iloc[0]
        kline_style = df["kline_style"].iloc[0]

        # 获取合约乘数
        symbol = instrument.rstrip("0123456789")
        vm = MULTIPLIERS.get(symbol, 10)
        strict_params["volume_multiple"] = vm
        loose_params["volume_multiple"] = vm

        df = calc_bbands(df, 20, 2.0)

        strict_trades = run_backtest(df, strict_params)
        loose_trades = run_backtest(df, loose_params)

        # 只绘制有交易的品种（宽松参数下）
        if len(strict_trades) > 0 or len(loose_trades) > 0:
            plot_instrument(df, strict_trades, loose_trades, instrument, filepath)
            summary.append(f"  {instrument} ({kline_style}): 严格={len(strict_trades)}笔, 宽松={len(loose_trades)}笔")

        # 打印简短状态
        print(f"  {instrument}: 严格={len(strict_trades)}, 宽松={len(loose_trades)}")

    print(f"\n{'='*60}")
    print("有交易的品种汇总：")
    if summary:
        for s in summary:
            print(s)
    else:
        print("  所有品种均无交易信号")
    print(f"\n所有图片已保存到: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
