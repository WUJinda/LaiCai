# -*- coding: utf-8 -*-
"""
布林带做空策略 - 独立回测脚本

基于 my_boll_strategy.py 的策略逻辑，完全独立运行，不依赖 InfiniTrader。

使用方式:
    python test_boll_backtest.py
    python test_boll_backtest.py --data ~/Desktop/quanda_exports/rb2601_kline.json
    python test_boll_backtest.py --bb-period 26 --bb-std 2.0 --volume 10
    python test_boll_backtest.py --mode relaxed
"""

import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")  # 无需 GUI 窗口，直接保存图片
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# matplotlib 中文支持
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# ============================================================
# 默认参数（与 my_boll_strategy.py 的 Params 一致）
# ============================================================
DEFAULT_PARAMS = {
    "bb_period": 20,
    "bb_std": 2.0,
    "order_volume": 10,
    "bandwidth_threshold": 0.25,
    "breakout_threshold": 0.02,
    # 品种合约信息（用于计算盈亏金额）
    "volume_multiple": 10,  # 合约乘数，沥青=10, 螺纹钢=10
    "margin_rate": 0.13,    # 保证金率
    "fee_rate": 0.0001,     # 手续费率（万分之几）
}

# 模式预设
MODE_PRESETS = {
    "strict": {"bandwidth_threshold": 0.25, "breakout_threshold": 0.02},
    "relaxed": {"bandwidth_threshold": 0.20, "breakout_threshold": 0.01},
}

DEFAULT_DATA_PATH = os.path.join(
    os.path.expanduser("~"), "Desktop", "quanda_exports", "ag2606_kline.json"
)


# ============================================================
# 数据加载
# ============================================================
def load_data(filepath: str) -> pd.DataFrame:
    """从 JSON 文件加载K线数据（InfiniTrader 导出格式）"""
    with open(filepath, "r", encoding="utf-8") as f:
        raw = json.load(f)

    records = raw.get("data", [])
    if not records:
        print(f"错误：文件 {filepath} 中没有数据")
        sys.exit(1)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    print(f"数据加载完成: {raw.get('instrument', '?')} ({raw.get('exchange', '?')})")
    print(f"  周期: {raw.get('kline_style', '?')}, 记录数: {len(df)}")
    print(f"  范围: {df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
    return df


# ============================================================
# 布林带计算
# ============================================================
def calc_bbands(df: pd.DataFrame, period: int, std_dev: float) -> pd.DataFrame:
    """计算布林带指标（纯 numpy/pandas 实现，不依赖 talib）"""
    close = pd.Series(df["close"].values.astype(float))

    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)  # ddof=0 与 talib 一致
    upper = middle + std_dev * std
    lower = middle - std_dev * std

    df["bb_upper"] = upper.values
    df["bb_middle"] = middle.values
    df["bb_lower"] = lower.values

    # 布林带带宽: (上轨 - 下轨) / 中轨
    df["bandwidth"] = np.where(
        middle.values > 0,
        (upper.values - lower.values) / middle.values,
        0,
    )

    return df


# ============================================================
# 交易模拟（核心逻辑，与 my_boll_strategy.py 一致）
# ============================================================
class Trade:
    """记录一笔完整的交易（开仓 -> 平仓）"""

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


def run_backtest(df: pd.DataFrame, params: dict) -> list[Trade]:
    """
    运行回测，模拟 my_boll_strategy.py 的策略逻辑。

    开空条件: 上下轨斜率同时>0 + 带宽>阈值 + 收盘价突破上轨*(1+突破阈值)
    平空条件: 持仓中价格回落到中轨以下
    """
    trades: list[Trade] = []
    open_trade: Trade | None = None

    monitoring = False
    trend_slope_window = 3
    bb_period = params["bb_period"]

    bb_upper = df["bb_upper"].values
    bb_middle = df["bb_middle"].values
    bb_lower = df["bb_lower"].values
    close_vals = df["close"].values

    for i in range(bb_period, len(df)):
        bw = df.iloc[i]["bandwidth"]

        if np.isnan(bb_upper[i]) or np.isnan(bb_middle[i]):
            continue

        # 斜率趋势确认
        if i >= bb_period + trend_slope_window - 1:
            upper_slope = (bb_upper[i] - bb_upper[i - trend_slope_window]) / (trend_slope_window - 1)
            lower_slope = (bb_lower[i] - bb_lower[i - trend_slope_window]) / (trend_slope_window - 1)
            trend_confirmed = upper_slope > 0 and lower_slope > 0
        else:
            trend_confirmed = False

        # 前置条件
        bandwidth_ok = bw > params["bandwidth_threshold"]
        preconditions_met = trend_confirmed and bandwidth_ok

        # 信号计算
        monitoring = preconditions_met

        # ---- 执行交易 (exec_signal) ----

        # 平仓逻辑: 持有空仓且价格回到中轨以下
        if open_trade is not None and close_vals[i] <= bb_middle[i]:
            open_trade.close(df.iloc[i]["date"], close_vals[i])
            trades.append(open_trade)
            open_trade = None

        # 开仓逻辑: 满足前置条件 + 突破上轨
        if open_trade is None and monitoring:
            breakout_price = bb_upper[i] * (1 + params["breakout_threshold"])
            if close_vals[i] > breakout_price:
                open_trade = Trade(df.iloc[i]["date"], close_vals[i], params["order_volume"])
                monitoring = False

    return trades


# ============================================================
# 收益计算
# ============================================================
def calc_pnl(trades: list[Trade], params: dict) -> pd.DataFrame:
    """计算每笔交易的盈亏"""
    records = []
    vm = params["volume_multiple"]
    fee_rate = params["fee_rate"]

    for t in trades:
        # 做空盈亏: (开仓价 - 平仓价) * 手数 * 合约乘数
        points = t.open_price - t.close_price
        gross_pnl = points * t.volume * vm
        # 手续费: 开仓和平仓各收一次
        fee = (t.open_price + t.close_price) * t.volume * vm * fee_rate
        net_pnl = gross_pnl - fee

        records.append({
            "开仓日期": t.open_date.strftime("%Y-%m-%d"),
            "开仓价": t.open_price,
            "平仓日期": t.close_date.strftime("%Y-%m-%d"),
            "平仓价": t.close_price,
            "手数": t.volume,
            "点数盈亏": round(points, 2),
            "手续费": round(fee, 2),
            "净盈亏": round(net_pnl, 2),
            "盈利": net_pnl > 0,
        })

    return pd.DataFrame(records)


# ============================================================
# 报告输出
# ============================================================
def print_report(trades_df: pd.DataFrame, params: dict):
    """打印回测报告"""
    print("\n" + "=" * 70)
    print("                    布林带做空策略 - 回测报告")
    print("=" * 70)

    # 策略参数
    print(f"\n策略参数:")
    print(f"  布林带周期: {params['bb_period']}, 标准差倍数: {params['bb_std']}")
    print(f"  带宽阈值: {params['bandwidth_threshold']}, 突破阈值: {params['breakout_threshold']}")
    print(f"  每次开仓手数: {params['order_volume']}")
    print(f"  合约乘数: {params['volume_multiple']}, 手续费率: {params['fee_rate']}")

    if trades_df.empty:
        print("\n  没有产生任何交易信号。")
        print("=" * 70)
        return

    # 交易明细
    print(f"\n交易明细 (共 {len(trades_df)} 笔):")
    print("-" * 70)
    for i, row in trades_df.iterrows():
        direction = "盈利" if row["盈利"] else "亏损"
        print(
            f"  #{i+1:2d}  开: {row['开仓日期']} @ {row['开仓价']:>8.1f}"
            f"  平: {row['平仓日期']} @ {row['平仓价']:>8.1f}"
            f"  净盈亏: {row['净盈亏']:>+10.1f}  [{direction}]"
        )

    # 汇总统计
    total = len(trades_df)
    wins = trades_df["盈利"].sum()
    losses = total - wins
    win_rate = wins / total * 100 if total > 0 else 0

    total_pnl = trades_df["净盈亏"].sum()
    avg_pnl = trades_df["净盈亏"].mean()
    max_win = trades_df["净盈亏"].max()
    max_loss = trades_df["净盈亏"].min()

    # 盈亏比
    avg_win = trades_df[trades_df["盈利"]]["净盈亏"].mean() if wins > 0 else 0
    avg_loss = abs(trades_df[~trades_df["盈利"]]["净盈亏"].mean()) if losses > 0 else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    # 累计收益曲线 & 最大回撤
    cumulative = trades_df["净盈亏"].cumsum()
    peak = cumulative.cummax()
    drawdown = cumulative - peak
    max_drawdown = drawdown.min()

    print("-" * 70)
    print(f"\n汇总统计:")
    print(f"  总交易次数: {total}")
    print(f"  盈利/亏损: {wins}/{losses}")
    print(f"  胜率: {win_rate:.1f}%")
    print(f"  总盈亏: {total_pnl:>+,.1f}")
    print(f"  平均每笔盈亏: {avg_pnl:>+,.1f}")
    print(f"  最大单笔盈利: {max_win:>+,.1f}")
    print(f"  最大单笔亏损: {max_loss:>+,.1f}")
    print(f"  盈亏比: {profit_loss_ratio:.2f}")
    print(f"  最大回撤: {max_drawdown:>+,.1f}")
    print("=" * 70)

    return cumulative


# ============================================================
# 图表输出
# ============================================================
def plot_backtest(df: pd.DataFrame, trades: list[Trade], cumulative_pnl: pd.Series, params: dict):
    """绘制回测图表"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})

    dates = df["date"]
    close = df["close"]

    # ---- 上图: 价格 + 布林带 + 交易标记 ----
    ax1.plot(dates, close, color="black", linewidth=0.8, label="收盘价")
    ax1.plot(dates, df["bb_upper"], "r--", linewidth=0.6, alpha=0.7, label="上轨")
    ax1.plot(dates, df["bb_middle"], "b--", linewidth=0.6, alpha=0.7, label="中轨")
    ax1.plot(dates, df["bb_lower"], "g--", linewidth=0.6, alpha=0.7, label="下轨")

    # 标记开仓点（红色向下三角 = 做空）
    # 标记平仓点（绿色向上三角 = 买回）
    for t in trades:
        ax1.scatter(
            t.open_date, t.open_price,
            marker="v", color="red", s=120, zorder=5, edgecolors="darkred"
        )
        ax1.scatter(
            t.close_date, t.close_price,
            marker="^", color="limegreen", s=120, zorder=5, edgecolors="darkgreen"
        )

    # 添加图例（避免重复标记）
    ax1.scatter([], [], marker="v", color="red", s=100, label="开空仓")
    ax1.scatter([], [], marker="^", color="limegreen", s=100, label="平空仓")

    ax1.set_title("布林带做空策略回测", fontsize=14, fontweight="bold")
    ax1.set_ylabel("价格")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(True, alpha=0.3)

    # ---- 下图: 累计收益曲线 ----
    if not cumulative_pnl.empty:
        # 为累计收益创建日期索引（用平仓日期）
        trade_dates = [t.close_date for t in trades]
        ax2.plot(trade_dates, cumulative_pnl.values, color="royalblue", linewidth=1.2)
        ax2.fill_between(
            trade_dates, cumulative_pnl.values, 0,
            where=cumulative_pnl.values >= 0, alpha=0.3, color="green"
        )
        ax2.fill_between(
            trade_dates, cumulative_pnl.values, 0,
            where=cumulative_pnl.values < 0, alpha=0.3, color="red"
        )
        ax2.axhline(y=0, color="gray", linewidth=0.5)

    ax2.set_title("累计收益", fontsize=12)
    ax2.set_ylabel("盈亏金额")
    ax2.set_xlabel("日期")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # 保存图表到文件
    output_path = os.path.join(os.path.dirname(__file__), "backtest_result.png")
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n图表已保存: {output_path}")


# ============================================================
# 命令行参数
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="布林带做空策略 - 独立回测脚本")
    parser.add_argument("--data", type=str, default=DEFAULT_DATA_PATH, help="K线数据文件路径 (JSON)")
    parser.add_argument("--bb-period", type=int, default=DEFAULT_PARAMS["bb_period"], help="布林带周期")
    parser.add_argument("--bb-std", type=float, default=DEFAULT_PARAMS["bb_std"], help="标准差倍数")
    parser.add_argument("--volume", type=int, default=DEFAULT_PARAMS["order_volume"], help="下单手数")
    parser.add_argument("--bandwidth", type=float, default=None, help="带宽阈值（覆盖模式预设）")
    parser.add_argument("--breakout", type=float, default=None, help="突破阈值（覆盖模式预设）")
    parser.add_argument("--mode", type=str, choices=["strict", "relaxed"], default="strict",
                        help="参数模式: strict(25%%/2%%) 或 relaxed(20%%/1%%)，默认 strict")
    parser.add_argument("--multiplier", type=int, default=DEFAULT_PARAMS["volume_multiple"], help="合约乘数")
    return parser.parse_args()


# ============================================================
# 主入口
# ============================================================
def main():
    args = parse_args()

    # 应用模式预设
    mode_preset = MODE_PRESETS[args.mode]

    # 合并参数（命令行 --bandwidth/--breakout 可覆盖模式预设）
    params = {
        **DEFAULT_PARAMS,
        "bb_period": args.bb_period,
        "bb_std": args.bb_std,
        "order_volume": args.volume,
        "bandwidth_threshold": args.bandwidth if args.bandwidth is not None else mode_preset["bandwidth_threshold"],
        "breakout_threshold": args.breakout if args.breakout is not None else mode_preset["breakout_threshold"],
        "volume_multiple": args.multiplier,
    }

    print(f"参数模式: {args.mode}")

    # 加载数据
    if not os.path.exists(args.data):
        print(f"错误：数据文件不存在: {args.data}")
        print(f"请确认文件路径，或使用 --data 指定文件")
        sys.exit(1)

    df = load_data(args.data)

    # 计算布林带
    df = calc_bbands(df, params["bb_period"], params["bb_std"])

    # 运行回测
    print(f"\n开始回测...")
    trades = run_backtest(df, params)
    print(f"回测完成，共产生 {len(trades)} 笔交易")

    # 计算盈亏
    trades_df = calc_pnl(trades, params)

    # 打印报告
    cumulative_pnl = print_report(trades_df, params)

    # 绘制图表
    if trades:
        plot_backtest(df, trades, cumulative_pnl, params)
    else:
        # 没有交易也要画出价格和布林带
        fig, ax = plt.subplots(figsize=(16, 6))
        ax.plot(df["date"], df["close"], color="black", linewidth=0.8, label="收盘价")
        ax.plot(df["date"], df["bb_upper"], "r--", linewidth=0.6, alpha=0.7, label="上轨")
        ax.plot(df["date"], df["bb_middle"], "b--", linewidth=0.6, alpha=0.7, label="中轨")
        ax.plot(df["date"], df["bb_lower"], "g--", linewidth=0.6, alpha=0.7, label="下轨")
        ax.set_title("布林带做空策略回测 (无交易信号)", fontsize=14)
        ax.set_ylabel("价格")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        output_path = os.path.join(os.path.dirname(__file__), "backtest_result.png")
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"\n图表已保存: {output_path}")


if __name__ == "__main__":
    main()
