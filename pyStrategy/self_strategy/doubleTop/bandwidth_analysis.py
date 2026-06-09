# -*- coding: utf-8 -*-
"""
布林带带宽统计分析工具
=====================
目的：统计各品种带宽分布特征，回答以下问题：
  1. 带宽大多数时间在什么范围？
  2. 市场波动较大时，带宽会到什么程度？
  3. 用什么统计指标描述最合适？

输出：
  - 各品种带宽的分位数统计表
  - 带宽分布直方图（保存为图片）
  - 跨品种带宽对比
  - 推荐的带宽阈值参考
"""

import json
import os
import glob
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ============================================================
# 配置
# ============================================================
# K线数据目录（按周期）
DATA_DIRS = {
    "H2": os.path.expanduser("~/Desktop/quanda_exports_h2"),
    "H4": os.path.expanduser("~/Desktop/quanda_exports_h4"),
    "D1": os.path.expanduser("~/Desktop/quanda_exports_d1"),
}

# 布林带参数（与策略一致）
BB_PERIODS = [20, 26]  # 测试两种常用周期
BB_STD = 2.0

# 品种名称映射
INSTRUMENT_NAMES = {
    "rb": "螺纹钢", "hc": "热卷", "cu": "铜", "al": "铝", "zn": "锌",
    "ni": "镍", "au": "黄金", "ag": "白银", "bu": "沥青", "ru": "橡胶",
    "i": "铁矿石", "m": "豆粕", "y": "豆油", "p": "棕榈油",
    "a": "豆一", "c": "玉米", "cs": "玉米淀粉",
    "SR": "白糖", "CF": "棉花", "RM": "菜粕", "MA": "甲醇",
    "TA": "PTA", "FG": "玻璃", "SA": "纯碱",
    "IC": "中证500", "IF": "沪深300", "IH": "上证50", "IM": "中证1000",
    "T": "10年国债", "TF": "5年国债", "TS": "2年国债",
}

# 交易所分类
EXCHANGE_MAP = {
    "rb": "上期所", "hc": "上期所", "cu": "上期所", "al": "上期所", "zn": "上期所",
    "ni": "上期所", "au": "上期所", "ag": "上期所", "bu": "上期所", "ru": "上期所",
    "i": "大商所", "m": "大商所", "y": "大商所", "p": "大商所",
    "a": "大商所", "c": "大商所", "cs": "大商所",
    "SR": "郑商所", "CF": "郑商所", "RM": "郑商所", "MA": "郑商所",
    "TA": "郑商所", "FG": "郑商所", "SA": "郑商所",
    "IC": "中金所", "IF": "中金所", "IH": "中金所", "IM": "中金所",
    "T": "中金所", "TF": "中金所", "TS": "中金所",
}


def extract_symbol(instrument_id: str) -> str:
    """从合约代码提取品种代码，如 rb2610 -> rb"""
    import re
    match = re.match(r"([a-zA-Z]+)", instrument_id)
    return match.group(1) if match else instrument_id


def calc_bband_width(close_array, period=20, std_dev=2.0):
    """计算布林带带宽序列"""
    close = pd.Series(close_array.astype(float))
    middle = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = np.where(middle > 0, (upper - lower) / middle, np.nan)
    return bandwidth


def load_kline_data(data_dir):
    """加载目录下所有K线JSON数据，返回 dict[symbol_code -> DataFrame]"""
    result = {}
    pattern = os.path.join(data_dir, "*_kline.json")
    files = sorted(glob.glob(pattern))

    for fpath in files:
        fname = os.path.basename(fpath)
        # 提取合约代码（如 rb2610）
        code = fname.replace("_kline.json", "")

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [跳过] {fname}: {e}")
            continue

        rows = data.get("data", [])
        if not rows:
            continue

        df = pd.DataFrame(rows)
        if "close" not in df.columns:
            continue

        df["date"] = pd.to_datetime(df["date"])
        df["close"] = df["close"].astype(float)
        df["code"] = code
        df["symbol"] = extract_symbol(code)

        # 用品种代码作为 key（如果有多个合约用最新的）
        if code not in result:
            result[code] = df
        else:
            # 保留数据量更多的那个
            if len(df) > len(result[code]):
                result[code] = df

    return result


def compute_bandwidth_stats(bw_series, label=""):
    """计算一组带宽序列的完整统计信息"""
    bw = bw_series[~np.isnan(bw_series)]
    if len(bw) == 0:
        return None

    stats = {
        "品种": label,
        "样本数": len(bw),
        "最小值": np.min(bw),
        "P5": np.percentile(bw, 5),
        "P10": np.percentile(bw, 10),
        "P25 (Q1)": np.percentile(bw, 25),
        "中位数 (P50)": np.median(bw),
        "均值": np.mean(bw),
        "P75 (Q3)": np.percentile(bw, 75),
        "P90": np.percentile(bw, 90),
        "P95": np.percentile(bw, 95),
        "P99": np.percentile(bw, 99),
        "最大值": np.max(bw),
        "标准差": np.std(bw, ddof=1),
        "偏度": pd.Series(bw).skew(),
        "IQR": np.percentile(bw, 75) - np.percentile(bw, 25),
    }
    # 变异系数
    stats["变异系数(CV)"] = stats["标准差"] / stats["均值"] if stats["均值"] > 0 else 0
    # 中位数/均值比 — 反映偏态程度
    stats["中位数/均值"] = stats["中位数 (P50)"] / stats["均值"] if stats["均值"] > 0 else 0

    return stats


def analyze_single_period(kline_dir, period_label, bb_period=20):
    """分析一个K线周期的所有品种带宽"""
    print(f"\n{'='*80}")
    print(f"  布林带带宽统计分析  |  K线周期: {period_label}  |  BB周期: {bb_period}  |  BB标准差: {BB_STD}")
    print(f"{'='*80}")

    all_data = load_kline_data(kline_dir)
    if not all_data:
        print("  未找到K线数据！")
        return None

    print(f"  共加载 {len(all_data)} 个合约的数据\n")

    # ---- 逐品种计算带宽统计 ----
    all_stats = []
    all_bw_data = {}  # code -> bandwidth array

    for code, df in sorted(all_data.items()):
        symbol = extract_symbol(code)
        bw = calc_bband_width(df["close"].values, period=bb_period, std_dev=BB_STD)

        # 过滤 NaN（前 bb_period-1 个为 NaN）
        bw_valid = bw[~np.isnan(bw)]
        if len(bw_valid) < 30:
            continue

        label = f"{symbol}({INSTRUMENT_NAMES.get(symbol, '')})"
        stats = compute_bandwidth_stats(bw, label)
        if stats:
            stats["合约"] = code
            stats["品种代码"] = symbol
            stats["交易所"] = EXCHANGE_MAP.get(symbol, "")
            all_stats.append(stats)
            all_bw_data[code] = bw_valid

    if not all_stats:
        print("  无有效数据！")
        return None

    stats_df = pd.DataFrame(all_stats)

    # ---- 按交易所分组打印 ----
    print(f"\n{'─'*80}")
    print(f"  各品种带宽分布统计（核心分位数表）")
    print(f"{'─'*80}")
    print(f"  说明: P50=中位数, 即50%时间带宽低于此值")
    print(f"        P90=90%时间带宽低于此值, 即带宽超过此值属于极端情况(前10%)")
    print(f"        P95=95%时间带宽低于此值, 即带宽超过此值属于极端情况(前5%)")
    print()

    # 打印表头
    col_order = [
        "品种", "交易所", "样本数",
        "P5", "P25 (Q1)", "中位数 (P50)", "均值",
        "P75 (Q3)", "P90", "P95", "P99", "最大值",
        "偏度", "IQR",
    ]
    display_df = stats_df[col_order].copy()

    # 格式化数值
    pct_cols = ["P5", "P25 (Q1)", "中位数 (P50)", "均值", "P75 (Q3)", "P90", "P95", "P99", "最大值", "IQR"]
    for c in pct_cols:
        display_df[c] = display_df[c].map(lambda x: f"{x:.4f}" if pd.notna(x) else "")
    display_df["偏度"] = display_df["偏度"].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")

    # 按交易所排序
    exchange_order = {"上期所": 0, "大商所": 1, "郑商所": 2, "中金所": 3}
    display_df["_sort"] = stats_df["交易所"].map(exchange_order)
    display_df = display_df.sort_values("_sort").drop(columns=["_sort"])

    pd.set_option("display.max_rows", 50)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 200)
    pd.set_option("display.unicode.ambiguous_as_wide", True)
    pd.set_option("display.unicode.east_asian_width", True)
    print(display_df.to_string(index=False))

    # ---- 汇总统计 ----
    print(f"\n{'─'*80}")
    print(f"  全品种汇总统计")
    print(f"{'─'*80}")

    # 把所有品种的带宽合并
    all_bw_combined = np.concatenate(list(all_bw_data.values()))
    combined_stats = compute_bandwidth_stats(all_bw_combined, "全品种合计")

    summary_keys = [
        "样本数", "最小值", "P5", "P25 (Q1)", "中位数 (P50)", "均值",
        "P75 (Q3)", "P90", "P95", "P99", "最大值", "标准差", "偏度", "变异系数(CV)",
    ]
    for k in summary_keys:
        val = combined_stats[k]
        if isinstance(val, float):
            print(f"  {k:16s}: {val:.4f}")
        else:
            print(f"  {k:16s}: {val}")

    # ---- 带宽区间分布分析 ----
    print(f"\n{'─'*80}")
    print(f"  带宽区间分布（各区间占比 %）")
    print(f"{'─'*80}")

    bins = [0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 1.0]
    bin_labels = ["<2%", "2-4%", "4-6%", "6-8%", "8-10%", "10-12%", "12-15%", "15-20%", "20-25%", "25-30%", "30-40%", "40-50%", "≥50%"]

    print(f"\n  {'品种':>12s}", end="")
    for bl in bin_labels:
        print(f"  {bl:>6s}", end="")
    print()

    for code in sorted(all_bw_data.keys()):
        symbol = extract_symbol(code)
        bw = all_bw_data[code]
        counts, _ = np.histogram(bw, bins=bins)
        pcts = counts / len(bw) * 100
        label = f"{symbol}"
        print(f"  {label:>12s}", end="")
        for p in pcts:
            if p > 0:
                print(f"  {p:5.1f}%", end="")
            else:
                print(f"  {'':>6s}", end="")
        print()

    # 全品种汇总分布
    counts_all, _ = np.histogram(all_bw_combined, bins=bins)
    pcts_all = counts_all / len(all_bw_combined) * 100
    print(f"  {'─── 全品种':>12s}", end="")
    for p in pcts_all:
        if p > 0:
            print(f"  {p:5.1f}%", end="")
        else:
            print(f"  {'':>6s}", end="")
    print()

    # ---- 各品种带宽阈值参考 ----
    print(f"\n{'─'*80}")
    print(f"  策略带宽阈值参考（按分位数推荐）")
    print(f"{'─'*80}")
    print(f"  含义: 如果设 bandwidth_threshold = X,")
    print(f"        则该品种大约有 Y% 的时间满足「带宽 > X」的条件")
    print()

    threshold_candidates = [0.10, 0.12, 0.15, 0.18, 0.20, 0.21, 0.25, 0.30]
    print(f"  {'品种':>8s} {'名称':>8s}", end="")
    for t in threshold_candidates:
        print(f"  >{t:.0%}", end="")
    print(f"  {'推荐区间':>20s}")
    print(f"  {'':>8s} {'':>8s}", end="")
    for t in threshold_candidates:
        print(f"  触发%", end="")
    print()

    for _, row in stats_df.iterrows():
        symbol = row["品种代码"]
        code = row["合约"]
        bw = all_bw_data[code]
        print(f"  {symbol:>8s} {INSTRUMENT_NAMES.get(symbol, ''):>8s}", end="")
        for t in threshold_candidates:
            pct = np.mean(bw > t) * 100
            print(f"  {pct:5.1f}", end="")
        # 推荐区间：P75~P95
        print(f"  {row['P75 (Q3)']:.3f}~{row['P95']:.3f}", end="")
        print()

    # ---- 跨品种对比排名 ----
    print(f"\n{'─'*80}")
    print(f"  带宽排名（按中位数从大到小）")
    print(f"{'─'*80}")
    ranked = stats_df.sort_values("中位数 (P50)", ascending=False)
    print(f"  {'排名':>4s}  {'品种':>8s}  {'中位数':>8s}  {'P95':>8s}  {'最大值':>8s}  {'偏度':>6s}  {'变异系数':>8s}")
    for i, (_, row) in enumerate(ranked.iterrows(), 1):
        print(f"  {i:>4d}  {row['品种']:>8s}  {row['中位数 (P50)']:>8.4f}  {row['P95']:>8.4f}  {row['最大值']:>8.4f}  {row['偏度']:>6.2f}  {row['变异系数(CV)']:>8.2f}")

    return stats_df, all_bw_data


def compare_periods(bb_period=20):
    """对比不同K线周期的带宽特征"""
    print(f"\n{'='*80}")
    print(f"  跨周期对比  |  BB周期: {bb_period}  |  BB标准差: {BB_STD}")
    print(f"{'='*80}")

    period_stats = {}
    for plabel, ddir in DATA_DIRS.items():
        if not os.path.isdir(ddir):
            continue
        data = load_kline_data(ddir)
        all_bw = []
        for code, df in data.items():
            bw = calc_bband_width(df["close"].values, period=bb_period, std_dev=BB_STD)
            bw_valid = bw[~np.isnan(bw)]
            if len(bw_valid) > 30:
                all_bw.append(bw_valid)

        if all_bw:
            combined = np.concatenate(all_bw)
            period_stats[plabel] = combined

    if not period_stats:
        print("  无可用数据")
        return

    # 对比表
    print(f"\n  {'统计量':>16s}", end="")
    for pl in period_stats:
        print(f"  {pl:>10s}", end="")
    print()

    stat_items = [
        ("中位数", lambda x: np.median(x)),
        ("均值", lambda x: np.mean(x)),
        ("P25", lambda x: np.percentile(x, 25)),
        ("P75", lambda x: np.percentile(x, 75)),
        ("P90", lambda x: np.percentile(x, 90)),
        ("P95", lambda x: np.percentile(x, 95)),
        ("P99", lambda x: np.percentile(x, 99)),
        ("最大值", lambda x: np.max(x)),
        ("标准差", lambda x: np.std(x, ddof=1)),
        ("偏度", lambda x: pd.Series(x).skew()),
    ]

    for name, func in stat_items:
        print(f"  {name:>16s}", end="")
        for pl in period_stats:
            val = func(period_stats[pl])
            print(f"  {val:>10.4f}", end="")
        print()


def compare_bb_periods(kline_dir, period_label):
    """对比不同BB参数下的带宽"""
    print(f"\n{'='*80}")
    print(f"  不同BB周期参数对比  |  K线: {period_label}")
    print(f"{'='*80}")

    data = load_kline_data(kline_dir)
    if not data:
        return

    all_bw_by_period = {}
    for bp in BB_PERIODS:
        all_bw = []
        for code, df in data.items():
            bw = calc_bband_width(df["close"].values, period=bp, std_dev=BB_STD)
            bw_valid = bw[~np.isnan(bw)]
            if len(bw_valid) > 30:
                all_bw.append(bw_valid)
        if all_bw:
            all_bw_by_period[bp] = np.concatenate(all_bw)

    print(f"\n  {'统计量':>16s}", end="")
    for bp in BB_PERIODS:
        print(f"  BB={bp:>3d}", end="")
    print()

    stat_items = [
        ("中位数", lambda x: np.median(x)),
        ("均值", lambda x: np.mean(x)),
        ("P90", lambda x: np.percentile(x, 90)),
        ("P95", lambda x: np.percentile(x, 95)),
        ("P99", lambda x: np.percentile(x, 99)),
        ("最大值", lambda x: np.max(x)),
    ]

    for name, func in stat_items:
        print(f"  {name:>16s}", end="")
        for bp in BB_PERIODS:
            if bp in all_bw_by_period:
                val = func(all_bw_by_period[bp])
                print(f"  {val:>7.4f}", end="")
        print()


# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 80)
    print("  布林带带宽统计分析工具")
    print("  目的：统计各品种带宽分布，找出最佳统计指标和策略阈值")
    print("=" * 80)

    # 1. 主要分析：H2 K线 + BB(20)
    h2_dir = DATA_DIRS["H2"]
    if os.path.isdir(h2_dir):
        result = analyze_single_period(h2_dir, "2小时线", bb_period=20)

    # 2. 跨周期对比
    compare_periods(bb_period=20)

    # 3. 不同BB参数对比
    for plabel, ddir in DATA_DIRS.items():
        if os.path.isdir(ddir):
            compare_bb_periods(ddir, f"{plabel}线")

    # ============================================================
    # 统计指标推荐说明
    # ============================================================
    print(f"\n{'='*80}")
    print(f"  统计指标选择建议")
    print(f"{'='*80}")
    print("""
  【为什么推荐用分位数（Percentile）而不是均值/标准差？】

  1. 中位数 (P50) vs 均值:
     - 带宽分布通常是右偏的（偏度 > 0），即有少数极端大值拉高了均值
     - 中位数不受极端值影响，更能反映"大多数时间"的带宽水平
     - 如果 中位数/均值 < 0.9，说明右偏明显，用中位数更可靠

  2. 分位数区间 (P25~P75, IQR) 的含义:
     - IQR (四分位距) = P75 - P25，即"中间50%时间"带宽的波动范围
     - 这是带宽的"日常波动区间"

  3. P90 / P95 / P99 的含义:
     - P95: 带宽超过此值的时间只占5%，属于"异常波动"
     - 适合作为策略中 bandwidth_threshold 的参考：
       设为P95意味着只在最波动的5%时间才会触发信号

  4. 推荐指标组合:
     - 日常水平: 中位数 + IQR (P25~P75)
     - 波动较大时: P90 + P95
     - 极端波动: P99 + 最大值
     - 策略阈值: P90~P95之间，根据品种特性微调

  5. 跨品种比较:
     - 变异系数(CV) = 标准差/均值，衡量相对离散程度
     - CV越大说明该品种带宽波动越剧烈，可能需要更灵活的阈值
""")

    print("  分析完成！")
