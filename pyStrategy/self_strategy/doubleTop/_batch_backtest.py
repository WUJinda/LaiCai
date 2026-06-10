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
# 按品种×周期分别选百分位（P75/P80/P85/P90）
# 规则：CV<0.55且偏度<1.5→P75，CV≥0.55或偏度≥1.5→P80，
#        CV≥0.70或偏度≥2.5→P85，CV≥0.75且偏度≥2.0→P90
# 排除：IC/IM/IF/IH（H4=D1数据重复）、T/TF/TS（国债带宽过小，不适合双顶策略）
# P80/P85 由 P75↔P90 线性插值
# ============================================================

# 排除的品种（国债期货：带宽过小，不适合双顶策略）
EXCLUDED_INSTRUMENTS = {"T", "TF", "TS"}


def is_instrument_excluded(instrument_id: str) -> bool:
    """判断品种是否被排除（如国债期货）"""
    iid = instrument_id.upper()
    for prefix in sorted(EXCLUDED_INSTRUMENTS, key=len, reverse=True):
        if iid.startswith(prefix):
            rest = iid[len(prefix):]
            if not rest or rest[0].isdigit():
                return True
    return False


# 每品种每周期 → 使用的百分位（全大写）
_INSTRUMENT_PERCENTILE = {
    # --- 异形波动组 (AG/AU/BU)：波动特征异常，使用更高百分位 ---
    "AG_H2": "P85", "AG_H4": "P85", "AG_D1": "P75",
    "AU_H2": "P90", "AU_H4": "P90", "AU_D1": "P90",
    "BU_H2": "P90", "BU_H4": "P90", "BU_D1": "P90",
    # --- 正常组 ---
    "CF_H2": "P80", "CF_H4": "P75", "CF_D1": "P75",
    "FG_H2": "P80", "FG_H4": "P75", "FG_D1": "P75",
    "MA_H2": "P80", "MA_H4": "P85", "MA_D1": "P85",
    "RM_H2": "P75", "RM_H4": "P75", "RM_D1": "P75",
    "SA_H2": "P85", "SA_H4": "P75", "SA_D1": "P75",
    "SR_H2": "P75", "SR_H4": "P75", "SR_D1": "P75",
    "TA_H2": "P90", "TA_H4": "P85", "TA_D1": "P85",
    "A_H2":  "P75", "A_H4":  "P75", "A_D1":  "P75",
    "AL_H2": "P80", "AL_H4": "P85", "AL_D1": "P80",
    "C_H2":  "P75", "C_H4":  "P75", "C_D1":  "P80",
    "CS_H2": "P75", "CS_H4": "P75", "CS_D1": "P75",
    "CU_H2": "P90", "CU_H4": "P80", "CU_D1": "P80",
    "HC_H2": "P85", "HC_H4": "P75", "HC_D1": "P75",
    "I_H2":  "P80", "I_H4":  "P75", "I_D1":  "P75",
    "M_H2":  "P75", "M_H4":  "P75", "M_D1":  "P75",
    "NI_H2": "P80", "NI_H4": "P85", "NI_D1": "P85",
    "P_H2":  "P75", "P_H4":  "P75", "P_D1":  "P80",
    "RB_H2": "P75", "RB_H4": "P75", "RB_D1": "P75",
    "RU_H2": "P85", "RU_H4": "P75", "RU_D1": "P75",
    "Y_H2":  "P80", "Y_H4":  "P75", "Y_D1":  "P75",
    "ZN_H2": "P75", "ZN_H4": "P80", "ZN_D1": "P75",
}


_BANDWIDTH_STATS_PATH = os.path.join(os.path.dirname(__file__), "bandwidth_stats.json")


def _interp_p80(p75, p90):
    """P75→P90 线性插值 P80"""
    return p75 + (p90 - p75) / 3.0


def _interp_p85(p75, p90):
    """P75→P90 线性插值 P85"""
    return p75 + (p90 - p75) * 2.0 / 3.0


def _get_threshold_for_pctile(val, pctile):
    """根据百分位选择阈值：P75/P80/P85/P90"""
    p75 = val.get("P75_Q3", 0)
    p90 = val.get("P90", 0)
    if pctile == "P90":
        return p90
    elif pctile == "P85":
        return _interp_p85(p75, p90)
    elif pctile == "P80":
        return _interp_p80(p75, p90)
    else:  # P75 (default)
        return p75


def _load_bandwidth_data():
    """从 bandwidth_stats.json 加载各品种各周期阈值，按 _INSTRUMENT_PERCENTILE 选分位"""
    try:
        with open(_BANDWIDTH_STATS_PATH, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    data = {}
    for key, val in stats.items():
        if key.startswith("_") or "_" not in key:
            continue
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym, period = parts
            lookup_key = f"{sym}_{period}".upper()
            # 查找该品种周期应使用的百分位
            pctile = _INSTRUMENT_PERCENTILE.get(lookup_key, "P75")
            threshold = _get_threshold_for_pctile(val, pctile)
            data[lookup_key] = {
                "threshold": threshold,
                "percentile": pctile,
                "P75": val.get("P75_Q3", 0),
                "P80": _interp_p80(val.get("P75_Q3", 0), val.get("P90", 0)),
                "P85": _interp_p85(val.get("P75_Q3", 0), val.get("P90", 0)),
                "P90": val.get("P90", 0),
            }
    return data


# 模块加载时读取一次
_BANDWIDTH_DATA = _load_bandwidth_data()

# 预排序（按品种代码长度降序），避免每次调用重复排序
_SORTED_BW_ITEMS = sorted(
    _BANDWIDTH_DATA.items(),
    key=lambda x: len(x[0].rsplit("_", 1)[0]),
    reverse=True,
)


def _find_bw_entry(instrument_id: str, kline_style: str = ""):
    """查找品种+周期对应的 _BANDWIDTH_DATA 条目，返回 (key, vals) 或 (None, None)"""
    iid = instrument_id.upper()
    ks = kline_style.upper()
    # 精确匹配：品种+周期
    for key, vals in _SORTED_BW_ITEMS:
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym, period = parts
            if iid.startswith(sym) and period == ks:
                return key, vals
    # 兜底：仅匹配品种
    for key, vals in _SORTED_BW_ITEMS:
        parts = key.rsplit("_", 1)
        if len(parts) == 2:
            sym = parts[0]
            if iid.startswith(sym):
                return key, vals
    return None, None


def get_bandwidth_threshold(instrument_id: str, kline_style: str = "") -> float:
    """根据合约代码+K线周期返回查表法带宽阈值"""
    _, vals = _find_bw_entry(instrument_id, kline_style)
    if vals is not None:
        return vals["threshold"]
    return 0.04  # 默认阈值


def get_bandwidth_percentile(instrument_id: str, kline_style: str = "") -> str:
    """返回该品种该周期使用的百分位标签"""
    _, vals = _find_bw_entry(instrument_id, kline_style)
    if vals is not None:
        return vals.get("percentile", "P75")
    return "P75"


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
    def __init__(self, open_idx, open_date, open_price, volume,
                 h_left=None, h_left_idx=-1, scan_start_idx=-1,
                 scan_end_idx=-1, zone_upper=None, bb_middle_at_entry=None):
        self.open_idx = open_idx
        self.open_date = open_date
        self.open_price = open_price
        self.volume = volume
        # 双顶字段（可选，供 run_band_lookup 使用）
        self.h_left = h_left
        self.h_left_idx = h_left_idx
        self.scan_start_idx = scan_start_idx
        self.scan_end_idx = scan_end_idx
        self.zone_upper = zone_upper
        self.bb_middle_at_entry = bb_middle_at_entry
        # 平仓字段
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
