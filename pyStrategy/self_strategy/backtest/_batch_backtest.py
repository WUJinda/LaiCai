# -*- coding: utf-8 -*-
"""
批量回测所有品种，生成结果报告（供 test_boll_backtest.py 调用）
"""

import json
import os

import numpy as np
import pandas as pd

# 合约乘数表（各品种）
MULTIPLIERS = {
    # 上期所 SHFE
    "rb": 10, "hc": 10, "cu": 5, "al": 5, "zn": 5,
    "ni": 1, "au": 1000, "ag": 15, "bu": 10, "ru": 10,
    # 大商所 DCE
    "i": 100, "m": 10, "y": 10, "p": 10, "a": 10, "c": 10, "cs": 10,
    # 郑商所 CZCE
    "SR": 10, "CF": 5, "RM": 10, "MA": 10, "TA": 5, "FG": 20, "SA": 20,
    # 中金所 CFFEX
    "IC": 200, "IF": 300, "IH": 300, "IM": 200,
    "T": 10000, "TF": 10000, "TS": 20000,
}


def get_multiplier(instrument_id: str) -> int:
    """根据合约代码提取品种并返回合约乘数"""
    for prefix, mult in MULTIPLIERS.items():
        if instrument_id.upper().startswith(prefix.upper()):
            return mult
    return 10  # 默认


def calc_bbands(close_array, period=20, std_dev=2.0):
    """计算布林带"""
    close = pd.Series(close_array.astype(float))
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = np.where(middle > 0, (upper - lower) / middle, 0)
    return upper.values, middle.values, lower.values, bandwidth


class Trade:
    def __init__(self, open_idx, open_date, open_price, volume):
        self.open_idx = open_idx
        self.open_date = open_date
        self.open_price = open_price
        self.volume = volume
        self.close_idx = None
        self.close_date = None
        self.close_price = None

    def close(self, close_idx, close_date, close_price):
        self.close_idx = close_idx
        self.close_date = close_date
        self.close_price = close_price


def run_single_backtest(df, params):
    """对单个 DataFrame 运行回测，返回 (trades, bbands_data)"""
    bb_period = params["bb_period"]
    bb_std = params["bb_std"]

    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, bb_period, bb_std
    )

    trades = []
    open_trade = None
    monitoring = False
    trend_slope_window = 3

    close_vals = df["close"].values

    for i in range(bb_period, len(df)):
        bb_upper = upper[i]
        bb_middle = middle[i]
        bw = bandwidth[i]

        if np.isnan(bb_upper) or np.isnan(bb_middle):
            continue

        # 斜率趋势确认
        if i >= bb_period + trend_slope_window - 1:
            upper_slope = (upper[i] - upper[i - trend_slope_window]) / (trend_slope_window - 1)
            lower_slope = (lower[i] - lower[i - trend_slope_window]) / (trend_slope_window - 1)
            trend_confirmed = upper_slope > 0 and lower_slope > 0
        else:
            trend_confirmed = False

        # 前置条件
        bandwidth_ok = bw > params["bandwidth_threshold"]
        preconditions_met = trend_confirmed and bandwidth_ok

        # 信号计算
        monitoring = preconditions_met

        # 平仓
        if open_trade is not None and close_vals[i] <= bb_middle:
            open_trade.close(i, df["date"].iloc[i], close_vals[i])
            trades.append(open_trade)
            open_trade = None

        # 开仓
        if open_trade is None and monitoring:
            breakout_price = bb_upper * (1 + params["breakout_threshold"])
            if close_vals[i] > breakout_price:
                open_trade = Trade(i, df["date"].iloc[i], close_vals[i], params["order_volume"])
                monitoring = False

    bbands_data = {"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth}
    return trades, bbands_data


def calc_trade_pnl(trades, volume_multiple, fee_rate):
    """计算交易盈亏明细"""
    results = []
    for t in trades:
        points = t.open_price - t.close_price
        gross = points * t.volume * volume_multiple
        fee = (t.open_price + t.close_price) * t.volume * volume_multiple * fee_rate
        net = gross - fee
        holding_days = (pd.Timestamp(t.close_date) - pd.Timestamp(t.open_date)).days
        results.append({
            "open_date": t.open_date,
            "open_price": t.open_price,
            "close_date": t.close_date,
            "close_price": t.close_price,
            "volume": t.volume,
            "holding_days": holding_days,
            "points": round(points, 2),
            "fee": round(fee, 2),
            "net_pnl": round(net, 2),
            "win": net > 0,
        })
    return results


def run_all_with_modes(data_dir, base_params):
    """批量运行两种模式（严谨+宽松）的回测"""
    strict_params = {**base_params, "bandwidth_threshold": 0.25, "breakout_threshold": 0.02}
    relaxed_params = {**base_params, "bandwidth_threshold": 0.20, "breakout_threshold": 0.01}
    return {
        "strict": run_all(data_dir, strict_params),
        "relaxed": run_all(data_dir, relaxed_params),
    }


def run_all(data_dir, params):
    """批量运行所有品种的回测"""
    all_results = []

    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith("_kline.json"):
            continue

        filepath = os.path.join(data_dir, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)

        records = raw.get("data", [])
        if len(records) < params["bb_period"] + 5:
            continue

        instrument = raw.get("instrument", fname.replace("_kline.json", ""))
        exchange = raw.get("exchange", "?")
        kline_style = raw.get("kline_style", "?")

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        vm = get_multiplier(instrument)

        trades, bbands = run_single_backtest(df, params)
        trade_details = calc_trade_pnl(trades, vm, params["fee_rate"])

        # 统计指标
        max_bw = float(np.nanmax(bbands["bandwidth"]))
        bw_above_threshold = float(np.nanmean(bbands["bandwidth"] > params["bandwidth_threshold"]) * 100)

        result = {
            "instrument": instrument,
            "exchange": exchange,
            "kline_style": kline_style,
            "records": len(df),
            "date_start": df["date"].iloc[0].strftime("%Y-%m-%d"),
            "date_end": df["date"].iloc[-1].strftime("%Y-%m-%d"),
            "max_bandwidth": round(max_bw, 4),
            "bw_above_pct": round(bw_above_threshold, 1),
            "volume_multiple": vm,
            "trade_count": len(trade_details),
            "trades": trade_details,
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

            # 累计收益和最大回撤
            cumulative = np.cumsum(pnls)
            peak = np.maximum.accumulate(cumulative)
            drawdown = cumulative - peak
            result["max_drawdown"] = round(float(drawdown.min()), 2)

        all_results.append(result)

    return all_results
