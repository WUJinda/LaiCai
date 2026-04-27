# 布林带做空策略 - 回测脚本使用说明

## 环境要求

- Python 3.12+
- 依赖包：`numpy`, `pandas`, `matplotlib`
- 不需要 InfiniTrader，不需要 talib（布林带用纯 pandas 计算）

安装依赖：
```bash
pip install numpy pandas matplotlib
```

## 文件清单

所有脚本位于 `pyStrategy/self_strategy/` 目录下：

| 文件 | 用途 |
|------|------|
| `test_boll_backtest.py` | 单品种回测（主入口，带图表输出） |
| `_batch_backtest.py` | 批量回测引擎库（被其他脚本调用） |
| `_backtest_h4.py` | H2 数据合并为 H4 后批量回测 |
| `_backtest_d1.py` | H2 数据合并为日线后批量回测 |
| `_generate_report.py` | H2 呟始周期批量回测 + 生成完整报告 |

## 数据格式

K 线数据为 JSON 文件，由 InfiniTrader 导出，格式如下：

```json
{
  "instrument": "ag2606",
  "exchange": "SHFE",
  "kline_style": "H2",
  "data": [
    {"date": "2026-01-02 09:00:00", "open": 6200, "high": 6250, "low": 6180, "close": 6230, "volume": 100},
    {"date": "2026-01-02 11:00:00", "open": 6230, "high": 6280, "low": 6210, "close": 6260, "volume": 120}
  ]
}
```

数据文件命名约定：`{品种代码}_kline.json`，例如 `ag2606_kline.json`、`rb2601_kline.json`。

## 运行命令

### 1. 单品种回测（test_boll_backtest.py）

最常用，对单个品种运行回测并生成图表。

```bash
# 默认：加载 ~/Desktop/quanda_exports/ag2606_kline.json，严谨模式
python pyStrategy/self_strategy/test_boll_backtest.py

# 指定数据文件
python pyStrategy/self_strategy/test_boll_backtest.py --data /path/to/rb2601_kline.json

# 宽松模式（带宽≥20%，突破+1%）
python pyStrategy/self_strategy/test_boll_backtest.py --data /path/to/data.json --mode relaxed

# 自定义参数
python pyStrategy/self_strategy/test_boll_backtest.py \
  --data /path/to/data.json \
  --bb-period 26 \
  --bb-std 2.0 \
  --volume 5 \
  --multiplier 10
```

**命令行参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--data` | `~/Desktop/quanda_exports/ag2606_kline.json` | K 线数据 JSON 文件路径 |
| `--mode` | `strict` | 参数模式：`strict`（带宽25%/突破2%）或 `relaxed`（带宽20%/突破1%） |
| `--bb-period` | 20 | 布林带 SMA 周期 |
| `--bb-std` | 2.0 | 标准差倍数 |
| `--volume` | 10 | 每次开仓手数 |
| `--bandwidth` | 由 mode 决定 | 带宽阈值（覆盖模式预设） |
| `--breakout` | 由 mode 决定 | 突破阈值（覆盖模式预设） |
| `--multiplier` | 10 | 合约乘数（用于计算盈亏金额） |

**输出：**
- 终端打印回测报告（交易明细 + 汇总统计）
- 生成图表：`pyStrategy/self_strategy/backtest_result.png`

**代码入口：**
- 主入口：`test_boll_backtest.py:431`
- 回测核心逻辑：`test_boll_backtest.py:125` `run_backtest()`
- 默认数据路径定义：`test_boll_backtest.py:51`

### 2. H4 周期批量回测（_backtest_h4.py）

将 H2 数据每 2 根合并为 1 根 H4 K 线，对所有品种批量回测。

```bash
python pyStrategy/self_strategy/_backtest_h4.py
```

**数据目录：** `~/Desktop/quanda_exports_h2/`，读取 `*_kline.json` 文件（`_backtest_h4.py:12`）

**输出报告：** `docs/res/backtest_report_h4.md`（`_backtest_h4.py:14`）

### 3. 日线周期批量回测（_backtest_d1.py）

将 H2 数据按日期合并为日线，对所有品种批量回测。

```bash
python pyStrategy/self_strategy/_backtest_d1.py
```

**数据目录：** `~/Desktop/quanda_exports_h2/`

**输出报告：** `docs/res/backtest_report_d1.md`（`_backtest_d1.py:15`）

### 4. H2 原始周期批量回测 + 图表（_generate_report.py）

直接使用 H2 数据批量回测，生成完整 Markdown 报告和每个品种的回测图表。

```bash
python pyStrategy/self_strategy/_generate_report.py
```

**数据目录：** `~/Desktop/quanda_exports_h2/`

**输出报告：** `docs/res/backtest_report_h2.md`

**输出图表：** `docs/res/backtest_{mode}_{品种}.png`

## 策略逻辑

### 开仓条件（做空）
1. 趋势确认：最近 3 根 K 线，上轨和下轨的斜率同时 > 0
2. 带宽过滤：布林带带宽 > 阈值（严谨 25%，宽松 20%）
3. 突破触发：收盘价 > 上轨 × (1 + 突破阈值)

### 平仓条件
- 持仓期间价格回落到布林带中轨以下时平仓

### 两种参数模式

| 参数 | 严谨模式 | 宽松模式 |
|------|---------|---------|
| 带宽阈值 | 25% | 20% |
| 突破阈值 | +2% | +1% |

## 合约乘数表

批量回测时自动根据品种代码匹配合约乘数（定义在 `_batch_backtest.py:13`）：

| 品种 | 乘数 | 品种 | 乘数 | 品种 | 乘数 |
|------|------|------|------|------|------|
| rb（螺纹钢） | 10 | cu（铜） | 5 | au（黄金） | 1000 |
| ag（白银） | 15 | i（铁矿） | 100 | ru（橡胶） | 10 |
| FG（玻璃） | 20 | SA（纯碱） | 20 | IF（沪深300） | 300 |

未在表中的品种默认乘数为 10。
