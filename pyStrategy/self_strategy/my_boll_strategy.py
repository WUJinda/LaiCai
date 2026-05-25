# ============================================================
# 布林带做空策略 (Bollinger Bands Short Strategy)
# ============================================================

from pythongo.base import BaseParams, BaseState, Field
from pythongo.classdef import KLineData, OrderData, TickData, TradeData
from pythongo.core import KLineStyleType
from pythongo.ui import BaseStrategy
from pythongo.utils import KLineGenerator


# ============================================================
# 资金管理常量
# ============================================================
MAX_PER_TRADE = 1_000_000       # 单笔交易保证金上限 100万
MAX_TOTAL_EXPOSURE = 6_000_000  # 同时持仓保证金上限 600万


# ============================================================
# 参数类 - 定义策略参数
# ============================================================
class Params(BaseParams):
    """参数映射模型 - 用户可在界面配置"""

    # 基础参数
    exchange: str = Field(default="", title="交易所代码")
    instrument_id: str = Field(default="", title="合约代码")
    kline_style: KLineStyleType = Field(default="M120", title="K线周期")

    # 布林带参数
    bb_period: int = Field(default=20, title="布林带周期", ge=2)
    bb_std: float = Field(default=2.0, title="标准差倍数", ge=0.1)

    # 交易参数
    pay_up: int | float = Field(default=0, title="超价")
    margin_rate: float = Field(default=0.10, title="保证金率", ge=0.01, le=1.0)

    # 策略参数
    bandwidth_threshold: float = Field(default=0.21, title="带宽阈值")
    breakout_threshold: float = Field(default=0.02, title="突破阈值")


# ============================================================
# 状态类 - 保存策略运行时的状态
# ============================================================
class State(BaseState):
    """状态映射模型 - 显示在界面上"""

    bb_upper: float = Field(default=0, title="上轨")
    bb_middle: float = Field(default=0, title="中轨")
    bb_lower: float = Field(default=0, title="下轨")
    bandwidth: float = Field(default=0, title="带宽")
    trend_confirmed: bool = Field(default=False, title="趋势已确认")
    monitoring: bool = Field(default=False, title="监听中")


# ============================================================
# 策略主类
# ============================================================
class BollingerBandsStrategy(BaseStrategy):
    """布林带做空策略"""

    def __init__(self):
        super().__init__()

        self.params_map = Params()
        """参数表"""

        self.state_map = State()
        """状态表"""

        self.kline_generator: KLineGenerator = None
        """K线合成器"""

        self.order_id: set[int] = set()
        """报单ID列表"""

        self.signal_price = 0
        """买卖信号价格标记"""

        self.trend_slope_window: int = 3
        """趋势斜率计算窗口（K线根数）"""

    # ========================================================
    # 主图指标 - 显示在K线图上
    # ========================================================
    @property
    def main_indicator_data(self) -> dict[str, float]:
        """返回主图指标数据"""
        return {
            "上轨": self.state_map.bb_upper,
            "中轨": self.state_map.bb_middle,
            "下轨": self.state_map.bb_lower
        }

    # ========================================================
    # 生命周期方法
    # ========================================================
    def on_start(self) -> None:
        """策略启动时调用"""
        self.kline_generator = KLineGenerator(
            callback=self.callback,
            real_time_callback=self.real_time_callback,
            exchange=self.params_map.exchange,
            instrument_id=self.params_map.instrument_id,
            style=self.params_map.kline_style
        )
        self.kline_generator.push_history_data()
        super().on_start()

    def on_tick(self, tick: TickData) -> None:
        """收到行情tick时调用"""
        super().on_tick(tick)
        self.kline_generator.tick_to_kline(tick)

    def on_stop(self) -> None:
        """策略停止时调用"""
        super().on_stop()

    def on_trade(self, trade: TradeData, log: bool = False) -> None:
        """成交回调"""
        super().on_trade(trade, log)
        if trade.order_id in self.order_id:
            self.order_id.remove(trade.order_id)

    def on_order_cancel(self, order: OrderData) -> None:
        """撤单回调"""
        super().on_order_cancel(order)
        if order.order_id in self.order_id:
            self.order_id.remove(order.order_id)

    # ========================================================
    # K线回调
    # ========================================================
    def callback(self, kline: KLineData) -> None:
        """K线完成时回调 — 更新指标和监控状态（不执行交易）"""

        # 1. 撤销上一根K线未成交的报单
        if len(self.order_id) > 0:
            for order_id in list(self.order_id):
                self.cancel_order(order_id)

        # 2. 计算布林带指标
        self.calc_indicator()

        # 3. 更新监控状态（状态机）
        self.calc_signal(kline)

        # 4. 更新图表
        self.widget.recv_kline({
            "kline": kline,
            "signal_price": self.signal_price,
            **self.main_indicator_data
        })

    def real_time_callback(self, kline: KLineData) -> None:
        """实时tick回调 — 检查实时价格是否触发入场/出场"""

        # 1. 更新指标（当前未完成K线的最新值）
        self.calc_indicator()

        # 2. 基于实时价格检查交易信号
        self.exec_signal(kline)

        # 3. 更新图表
        self.widget.recv_kline({
            "kline": kline,
            "signal_price": self.signal_price,
            **self.main_indicator_data
        })

    # ========================================================
    # 指标计算
    # ========================================================
    def calc_indicator(self) -> None:
        """计算布林带指标"""
        upper, middle, lower = self.kline_generator.producer.bbands(
            period=self.params_map.bb_period,
            std_dev=self.params_map.bb_std,
            array=True
        )

        self.state_map.bb_upper = upper[-1]
        self.state_map.bb_middle = middle[-1]
        self.state_map.bb_lower = lower[-1]

        if self.state_map.bb_middle > 0:
            self.state_map.bandwidth = (
                (self.state_map.bb_upper - self.state_map.bb_lower)
                / self.state_map.bb_middle
            )

        n = self.trend_slope_window
        if len(upper) >= n:
            upper_slope = (upper[-1] - upper[-n]) / (n - 1)
            lower_slope = (lower[-1] - lower[-n]) / (n - 1)
            self.state_map.trend_confirmed = upper_slope > 0 and lower_slope > 0
        else:
            self.state_map.trend_confirmed = False

    # ========================================================
    # 信号计算 — 状态机（仅在K线完成时调用）
    # ========================================================
    def calc_signal(self, kline: KLineData) -> None:
        """更新监控状态

        状态机规则：
        - IDLE → MONITORING: 趋势确认 + 带宽达标
        - MONITORING → IDLE: 趋势被打破（上下轨不再同时向上）
        - MONITORING 一旦进入就保持，直到趋势被打破，
          不会因为带宽暂时回落而退出监控。
        """

        # 趋势被打破 → 退出监控
        if not self.state_map.trend_confirmed:
            self.state_map.monitoring = False
            return

        # 前置条件满足 → 进入监控（如果已在监控中则保持）
        if self.check_preconditions():
            self.state_map.monitoring = True

    def check_preconditions(self) -> bool:
        """检查前置条件"""
        if not self.state_map.trend_confirmed:
            return False
        return self.state_map.bandwidth > self.params_map.bandwidth_threshold

    # ========================================================
    # 交易执行 — 基于实时价格（在 real_time_callback 中调用）
    # ========================================================
    def exec_signal(self, kline: KLineData) -> None:
        """检查实时价格是否触发入场或出场

        平仓和开仓互斥：
        - 持有空仓 → 只检查平仓条件
        - 空仓 + 监控中 → 只检查开仓条件
        - 有挂单时 → 不重复下单
        """

        self.signal_price = 0
        position = self.get_position(self.params_map.instrument_id)
        has_pending = len(self.order_id) > 0

        # ========== 平仓逻辑 ==========
        if position.net_position < 0 and not has_pending:
            if kline.close <= self.state_map.bb_middle:
                self.signal_price = kline.close

                if self.trading:
                    order_id = self.auto_close_position(
                        exchange=self.params_map.exchange,
                        instrument_id=self.params_map.instrument_id,
                        volume=abs(position.net_position),
                        price=kline.close + self.params_map.pay_up,
                        order_direction="buy"
                    )
                    self.order_id.add(order_id)
                    self.output(f"平空仓: 价格回到中轨, 平仓价={kline.close}")
                return

        # ========== 开仓逻辑 ==========
        if position.net_position == 0 and self.state_map.monitoring and not has_pending:
            breakout_price = self.state_map.bb_upper * (1 + self.params_map.breakout_threshold)

            if kline.close > breakout_price:
                self.signal_price = -kline.close

                if self.trading:
                    volume = self.calc_volume(kline.close)
                    if volume > 0:
                        order_id = self.send_order(
                            exchange=self.params_map.exchange,
                            instrument_id=self.params_map.instrument_id,
                            volume=volume,
                            price=kline.close - self.params_map.pay_up,
                            order_direction="sell"
                        )
                        self.order_id.add(order_id)
                        self.output(
                            f"开空仓: 突破上轨+{self.params_map.breakout_threshold*100:.0f}%, "
                            f"开仓价={kline.close}, 上轨={self.state_map.bb_upper:.2f}, "
                            f"手数={volume}"
                        )

                # 开仓后退出监控，等待下次前置条件
                self.state_map.monitoring = False

    # ========================================================
    # 资金管理 — 动态计算下单手数
    # ========================================================
    def calc_volume(self, price: float) -> int:
        """根据资金管理原则动态计算下单手数

        合约乘数从平台获取，保证金率由用户配置（默认10%）。
        规则：
        - 单笔保证金 ≤ 100万
        - 同时持仓保证金 ≤ 600万
        """
        instrument = self.get_instrument_data(
            self.params_map.exchange,
            self.params_map.instrument_id
        )
        multiplier = instrument.size

        if multiplier <= 0:
            return 0

        margin_per_lot = price * multiplier * self.params_map.margin_rate
        if margin_per_lot <= 0:
            return 0

        max_by_trade = int(MAX_PER_TRADE // margin_per_lot)
        max_by_total = int(MAX_TOTAL_EXPOSURE // margin_per_lot)
        volume = min(max_by_trade, max_by_total)

        return max(volume, 1)
