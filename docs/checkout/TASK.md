# Boll策略可视化任务

## 目标
创建可视化脚本，对31个品种的K线数据运行布林带做空策略回测，绘制K线图+布林带+交易标注，输出PNG图片到 docs/checkout/ 目录。

## 参考文件
- 现有回测脚本：`pyStrategy/self_strategy/test_boll_backtest.py`（包含完整的回测逻辑、布林带计算、数据加载、绘图函数）
- K线数据目录：`C:\Users\Administrator\Desktop\quanda_exports\`（31个品种的JSON文件）

## 要求

### 1. 脚本：`docs/checkout/plot_boll.py`
基于 test_boll_backtest.py 改造，增加以下功能：

### 2. 两组参数对比
- **严格参数**（原始）：bw=0.25, breakout=0.02, consecutive=3
- **宽松参数**：bw=0.10, breakout=0.0, consecutive=1

### 3. 图表内容（每个品种一张图）
**上半部分 - K线+布林带：**
- 黑色线：收盘价
- 红色虚线：上轨
- 蓝色虚线：中轨
- 绿色虚线：下轨
- 严格参数交易标注：红色向下三角（开空）+ 绿色向上三角（平空）
- 宽松参数交易标注：橙色向下三角（开空）+ 蓝色向上三角（平空）
- 用竖线+半透明矩形标出交易区间（开仓到平仓）
- 标题包含品种名、参数信息

**下半部分 - 带宽曲线：**
- 紫色线：布林带带宽
- 红色水平虚线：严格阈值 bw=0.25
- 橙色水平虚线：宽松阈值 bw=0.10
- 标注产生交易的K线位置

### 4. 自动批量处理
- 遍历 `C:\Users\Administrator\Desktop\quanda_exports\*.json` 所有文件
- 每个品种自动生成一张图，文件名如 `ag2606_boll.png`
- 最后生成一个汇总信息（哪些品种有交易、几笔）

### 5. 技术要求
- matplotlib Agg 后端（无GUI）
- 中文字体：SimHei 或 Microsoft YaHei
- dpi=150，figsize=(18, 10)
- 品种合约乘数（用于盈亏计算）：
  ag=15, au=1000, cu=5, al=5, zn=5, ni=1, bu=10, rb=10, hc=10, i=100, ru=10,
  FG=20, SA=20, TA=5, MA=10, RM=10, SR=10, CF=5, c=10, cs=10, m=10, a=10, p=10, y=10,
  IF=300, IC=200, IH=300, IM=200, T=10000, TF=10000, TS=20000

### 6. 执行
创建好脚本后，运行它生成所有图片。
