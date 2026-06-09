# -*- coding: utf-8 -*-
"""
批量回测所有品种，生成结果报告（供 test_boll_backtest.py 调用）
"""

import json
import os

import numpy as np
import pandas as pd

# ============================================================
# 资金管理（敞口口径）
# ============================================================
TOTAL_CAPITAL = 10_000_000      # 总敞口资金 1000万
MAX_PER_TRADE = 1_000_000       # 单笔交易上限 100万
MAX_TOTAL_EXPOSURE = 6_000_000  # 同时持仓上限 600万 (60%)

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

# 保证金率表（各品种）
MARGIN_RATES = {
    # 上期所 SHFE
    "rb": 0.10, "hc": 0.10, "cu": 0.10, "al": 0.10, "zn": 0.10,
    "ni": 0.12, "au": 0.10, "ag": 0.12, "bu": 0.10, "ru": 0.10,
    # 大商所 DCE
    "i": 0.12, "m": 0.10, "y": 0.10, "p": 0.10, "a": 0.10, "c": 0.10, "cs": 0.10,
    # 郑商所 CZCE
    "SR": 0.10, "CF": 0.10, "RM": 0.10, "MA": 0.10, "TA": 0.10, "FG": 0.10, "SA": 0.10,
    # 中金所 CFFEX
    "IC": 0.12, "IF": 0.12, "IH": 0.12, "IM": 0.12,
    "T": 0.03, "TF": 0.03, "TS": 0.03,
}


def get_multiplier(instrument_id: str) -> int:
    """根据合约代码提取品种并返回合约乘数"""
    for prefix, mult in MULTIPLIERS.items():
        if instrument_id.upper().startswith(prefix.upper()):
            return mult
    return 10  # 默认


def get_margin_rate(instrument_id: str) -> float:
    """根据合约代码提取品种并返回保证金率"""
    for prefix, rate in MARGIN_RATES.items():
        if instrument_id.upper().startswith(prefix.upper()):
            return rate
    return 0.10  # 默认10%


# ============================================================
# 查表法带宽阈值（各品种各周期，来自 bandwidth_stats.json）
# ag（白银）使用 P90，其余品种全部使用 P75
# ============================================================
_P90_INSTRUMENTS = {"AG"}  # 使用 P90 的品种列表
_BANDWIDTH_STATS_PATH = os.path.join(os.path.dirname(__file__), "bandwidth_stats.json")


def _load_bandwidth_data():
    """从 bandwidth_stats.json 加载各品种各周期的 P75/P90，ag 用 P90，其余用 P75"""
    try:
        with open(_BANDWIDTH_STATS_PATH, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    # 构建完整阈值表
    data = {}
    for key, val in stats.items():
        if key.startswith("_") or "_" not in key:
            continue
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym, period = parts
            lookup_key = f"{sym}_{period}".upper()
            use_p90 = sym.upper() in _P90_INSTRUMENTS
            pct_key = "P90" if use_p90 else "P75_Q3"
            data[lookup_key] = {
                "threshold": val.get(pct_key, val.get("P75_Q3", 0.04)),
                "percentile": "P90" if use_p90 else "P75",
                "P75": val.get("P75_Q3", 0),
                "P90": val.get("P90", 0),
            }
    return data


# 模块加载时读取一次
_BANDWIDTH_DATA = _load_bandwidth_data()


def get_bandwidth_threshold(instrument_id: str, kline_style: str = "") -> float:
    """根据合约代码+K线周期返回查表法带宽阈值（自动选P75或P90）"""
    # 按品种代码长度降序排列，避免 "A" 抢先匹配 "AG"
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
    # 回退：只用品种匹配
    for key, vals in sorted_items:
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym = parts[0]
            if instrument_id.upper().startswith(sym):
                return vals["threshold"]
    return 0.04  # 默认阈值


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
    volume_multiple = params["volume_multiple"]
    margin_rate = params["margin_rate"]

    upper, middle, lower, bandwidth = calc_bbands(
        df["close"].values, bb_period, bb_std
    )

    trades = []
    open_trade = None
    monitoring = False
    trend_slope_window = 3
    current_margin = 0  # 当前持仓保证金

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
            current_margin -= open_trade.open_price * volume_multiple * margin_rate * open_trade.volume
            trades.append(open_trade)
            open_trade = None

        # 开仓
        if open_trade is None and monitoring:
            breakout_price = bb_upper * (1 + params["breakout_threshold"])
            if close_vals[i] > breakout_price:
                price = close_vals[i]
                margin_per_lot = price * volume_multiple * margin_rate
                # 单笔保证金不超100万，总保证金不超600万
                max_by_trade = int(MAX_PER_TRADE // margin_per_lot) if margin_per_lot > 0 else 0
                remaining = MAX_TOTAL_EXPOSURE - current_margin
                max_by_total = int(remaining // margin_per_lot) if margin_per_lot > 0 else 0
                volume = min(max_by_trade, max_by_total)

                if volume > 0:
                    open_trade = Trade(i, df["date"].iloc[i], price, volume)
                    current_margin += price * volume_multiple * margin_rate * volume
                    monitoring = False

    bbands_data = {"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth}
    return trades, bbands_data


def calc_trade_pnl(trades, volume_multiple, fee_rate, margin_rate):
    """计算交易盈亏明细"""
    results = []
    for t in trades:
        points = t.open_price - t.close_price
        gross = points * t.volume * volume_multiple
        fee = (t.open_price + t.close_price) * t.volume * volume_multiple * fee_rate
        net = gross - fee
        margin = t.open_price * t.volume * volume_multiple * margin_rate
        return_rate = net / margin * 100 if margin > 0 else 0
        holding_days = (pd.Timestamp(t.close_date) - pd.Timestamp(t.open_date)).days
        results.append({
            "open_date": t.open_date,
            "open_price": t.open_price,
            "close_date": t.close_date,
            "close_price": t.close_price,
            "volume": t.volume,
            "holding_days": holding_days,
            "margin": round(margin, 2),
            "points": round(points, 2),
            "fee": round(fee, 2),
            "net_pnl": round(net, 2),
            "return_rate": round(return_rate, 2),
            "win": net > 0,
        })
    return results


def run_all_with_modes(data_dir, base_params):
    """批量运行两种模式（严谨+宽松）的回测"""
    strict_params = {**base_params, "bandwidth_threshold": 0.21, "breakout_threshold": 0.02}
    relaxed_params = {**base_params, "bandwidth_threshold": 0.15, "breakout_threshold": 0.01}
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
        mr = get_margin_rate(instrument)
        bw_threshold = get_bandwidth_threshold(instrument, kline_style)
        params_with_vm = {**params, "volume_multiple": vm, "margin_rate": mr, "bandwidth_threshold": bw_threshold}

        trades, bbands = run_single_backtest(df, params_with_vm)
        trade_details = calc_trade_pnl(trades, vm, params["fee_rate"], mr)

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
            "margin_rate": mr,
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

            total_margin = sum(t["margin"] for t in trade_details)
            result["total_margin"] = round(total_margin, 2)
            result["avg_return_rate"] = round(
                sum(t["return_rate"] for t in trade_details) / len(trade_details), 2
            )

        all_results.append(result)

    return all_results
