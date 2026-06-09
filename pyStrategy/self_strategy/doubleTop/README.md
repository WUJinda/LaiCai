# 双峰/BOLL 做空策略

本目录包含两种基于布林带的做空策略：**BOLL 做空策略** 和 **双峰做空策略**，以及配套的回测、统计分析工具。

## 目录结构

```
doubleTop/
├── my_boll_strategy.py          ← BOLL策略实盘脚本
├── my_double_top_strategy.py    ← 双峰策略实盘脚本
├── _batch_backtest.py           ← 回测引擎（含查表法、资金管理）
├── _backtest_merged.py          ← 融合回测（H2/H4/D1 统一报告）
├── run_band_lookup.py           ← 查表法回测入口（生成报告+图表）
├── double_top_backtest.py       ← 双峰策略独立回测（自包含）
├── bandwidth_analysis.py        ← 带宽统计分析脚本
├── bandwidth_stats.json         ← 31品种×3周期带宽统计表
├── results/                     ← 回测结果
│   ├── band_lookup/             ← 查表法回测结果（报告+图表）
│   └── double_top/              ← 双峰回测结果（报告+图表）
└── README.md                    ← 本文件
```

---

## 一、BOLL 做空策略

### 策略概述

专注捕捉大行情做空机会。基于布林带扩张后的价格突破来寻找做空时机。支持 H2/H4/D1 多周期。

### 开仓条件

**前置条件（同时满足）：**
1. 布林带上轨和下轨均处于上涨状态（连续3根K线斜率 > 0）
2. 布林带带宽 > 该品种该周期的查表阈值（`bandwidth_stats.json`）
   - ag（白银）使用 P90 分位数
   - 其余品种使用 P75 分位数

**触发条件：**
- 收盘价突破上轨 × 1.01（即超过上轨 1%）

### 平仓条件

- 价格回落到布林带中轨以下

### 资金管理

| 规则 | 数值 |
|------|------|
| 总资金 | 1000 万 |
| 单笔保证金上限 | 100 万 |
| 同时持仓保证金上限 | 600 万 |
| 手数计算 | 动态计算 |

### 布林带参数

| 参数 | 默认值 |
|------|--------|
| bb_period | 20 |
| bb_std | 2.0 |
| breakout_threshold | 0.01 |

---

## 二、双峰做空策略

### 策略概述

日线周期做空策略，基于双顶形态 + 左侧交易思路。当价格经历一个显著高点（左峰）后回调到布林中轨，再次反弹接近左峰区间时直接做空，价格回到中轨时止盈。

### 核心逻辑

```
布林带宽 > 10% → 价格回调到中轨 → 回溯30日找左峰(H_left)
→ 价格反弹到 [0.99×H_left, 1.02×H_left] → 左侧交易直接做空
→ 价格回到中轨 → 平仓止盈
```

### 状态机

| 状态 | 含义 | 行为 |
|------|------|------|
| IDLE (0) | 空闲等待 | 等带宽达标 |
| WAITING_PULLBACK (1) | 等待回调 | 等价格触及中轨 |
| LEFT_PEAK_FOUND (2) | 左峰确认 | 等价格回到区间做空 / 突破失效 |
| IN_POSITION (3) | 持仓中 | 等价格回到中轨止盈 |

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `bb_period` | 20 | 布林带周期 |
| `bb_std` | 2.0 | 标准差倍数 |
| `bandwidth_min` | 0.10 | 最小带宽 |
| `left_peak_lookback` | 30 | 回溯K线数查找左峰 |
| `zone_lower` | 0.99 | 区间下沿（左峰倍数） |
| `zone_upper` | 1.02 | 区间上沿（左峰倍数） |

---

## 三、回测工具

### 环境要求

- Python 3.12+
- 依赖：`numpy`, `pandas`, `matplotlib`
- 不需要 InfiniTrader、不需要 talib

### 3.1 查表法回测（推荐）

使用各品种各周期的统计阈值进行回测，生成报告和过程图表。

```bash
python run_band_lookup.py
```

**输出：** `results/band_lookup/` 目录下：
- `backtest_band_lookup.md` — 完整报告（阈值表 + 交易详情 + 监控窗口标注）
- `chart_*.png` — 各品种交易过程图（OHLC + 布林带 + 监控窗口 + 开平仓标记）

### 3.2 双峰策略回测

```bash
python double_top_backtest.py                          # 批量回测所有品种（默认D1目录）
python double_top_backtest.py --instrument rb2605      # 只回测指定品种
python double_top_backtest.py --data-dir <path>        # 指定数据目录
python double_top_backtest.py --no-chart               # 跳过图表生成
```

**输出：** `results/double_top/` 目录

### 3.3 融合回测（H2/H4/D1）

```bash
python _backtest_merged.py
```

**输出：** `results/` 目录

### K线数据

数据文件位于桌面：
- H2: `~/Desktop/quanda_exports_h2/`
- H4: `~/Desktop/quanda_exports_h4/`
- D1: `~/Desktop/quanda_exports_d1/`

### 合约乘数表

| 品种 | 乘数 | 品种 | 乘数 | 品种 | 乘数 |
|------|------|------|------|------|------|
| rb（螺纹钢） | 10 | cu（铜） | 5 | au（黄金） | 1000 |
| ag（白银） | 15 | i（铁矿） | 100 | ru（橡胶） | 10 |
| FG（玻璃） | 20 | SA（纯碱） | 20 | IF（沪深300） | 300 |

---

## 四、带宽统计分析

带宽统计表 `bandwidth_stats.json` 包含 31 个品种 × 3 个周期（H2/H4/D1）的完整带宽分布：

- 百分位：P1, P5, P10, P25, P50（中位数）, P75, P90, P95, P99
- 统计量：均值、标准差、偏度、变异系数

可通过 Claude Skill `/bandwidth-analysis` 查询：
- 无参数 → 显示所有品种概览
- 品种代码（如 `ag`）→ 查询详细统计
- 数据目录路径 → 运行完整分析
