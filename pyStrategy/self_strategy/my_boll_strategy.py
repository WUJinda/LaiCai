# ============================================================
# 布林带做空策略 (Bollinger Bands Short Strategy)
# ============================================================

from pythongo.base import BaseParams, BaseState, Field
from pythongo.classdef import KLineData, OrderData, TickData, TradeData
from pythongo.core import KLineStyleType
from pythongo.ui import BaseStrategy
from pythongo.utils import KLineGenerator


# ============================================================
# 参数类 - 定义策略参数
# ============================================================
class Params(BaseParams):
    """参数映射模型 - 用户可在界面配置"""

    # 基础参数
    exchange: str = Field(default="", title="交易所代码")
    instrument_id: str = Field(default="", title="合约代码")
    kline_style: KLineStyleType = Field(default="M120", title="K线周期")  # 2小时=120分钟

    # 布林带参数
    bb_period: int = Field(default=20, title="布林带周期", ge=2)
    bb_std: float = Field(default=2.0, title="标准差倍数", ge=0.1)

    # 交易参数
    order_volume: int = Field(default=10, title="下单手数", ge=1)  # 10手
    pay_up: int | float = Field(default=0, title="超价")

    # 策略参数
    bandwidth_threshold: float = Field(default=0.25, title="带宽阈值")  # 25%
    breakout_threshold: float = Field(default=0.02, title="突破阈值")   # 2%


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

        self.pre_bb_upper = 0
        """上一根K线上轨"""

        self.pre_bb_lower = 0
        """上一根K线下轨"""

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
        # 初始化K线合成器
        self.kline_generator = KLineGenerator(
            callback=self.callback,
            real_time_callback=self.real_time_callback,
            exchange=self.params_map.exchange,
            instrument_id=self.params_map.instrument_id,
            style=self.params_map.kline_style
        )

        # 加载历史数据
        self.kline_generator.push_history_data()

        # 调用父类启动
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
        """K线完成时调用 - 核心逻辑入口"""

        # 1. 撤销未成交订单
        if len(self.order_id) > 0:
            for order_id in list(self.order_id):
                self.cancel_order(order_id)

        # 2. 计算布林带指标
        self.calc_indicator()

        # 3. 计算交易信号
        self.calc_signal(kline)

        # 4. 执行交易
        self.exec_signal(kline)

        # 5. 更新图表
        self.widget.recv_kline({
            "kline": kline,
            "signal_price": self.signal_price,
            **self.main_indicator_data
        })

    def real_time_callback(self, kline: KLineData) -> None:
        """实时K线回调 - 只更新图表，不交易"""
        self.calc_indicator()

        self.widget.recv_kline({
            "kline": kline,
            **self.main_indicator_data
        })

    # ========================================================
    # 指标计算
    # ========================================================
    def calc_indicator(self) -> None:
        """计算布林带指标"""
        # 获取布林带数据（返回数组）
        upper, middle, lower = self.kline_generator.producer.bbands(
            period=self.params_map.bb_period,
            std_dev=self.params_map.bb_std,
            array=True
        )

        # 保存上一根K线的值
        self.pre_bb_upper = self.state_map.bb_upper
        self.pre_bb_lower = self.state_map.bb_lower

        # 更新当前值（取数组最后两个元素）
        self.state_map.bb_upper = upper[-1]
        self.state_map.bb_middle = middle[-1]
        self.state_map.bb_lower = lower[-1]

        # 计算带宽: (上轨 - 下轨) / 中轨
        if self.state_map.bb_middle > 0:
            self.state_map.bandwidth = (
                (self.state_map.bb_upper - self.state_map.bb_lower)
                / self.state_map.bb_middle
            )

        # 判断趋势：上下轨在最近N根K线内是否同时向上（斜率>0）
        n = self.trend_slope_window
        if len(upper) >= n:
            upper_slope = (upper[-1] - upper[-n]) / (n - 1)
            lower_slope = (lower[-1] - lower[-n]) / (n - 1)
            self.state_map.trend_confirmed = upper_slope > 0 and lower_slope > 0
        else:
            self.state_map.trend_confirmed = False

    # ========================================================
    # 信号计算
    # ========================================================
    def calc_signal(self, kline: KLineData) -> None:
        """计算交易信号"""

        # 检查前置条件
        if self.check_preconditions():
            # 满足前置条件，开始监听
            self.state_map.monitoring = True
        else:
            # 不满足前置条件，停止监听
            self.state_map.monitoring = False

    def check_preconditions(self) -> bool:
        """检查前置条件（首要门槛）"""
        # 条件1: 上下轨在最近3根K线内同时向上（斜率>0）
        if not self.state_map.trend_confirmed:
            return False

        # 条件2: 带宽超过阈值
        return self.state_map.bandwidth > self.params_map.bandwidth_threshold

    # ========================================================
    # 交易执行
    # ========================================================
    def exec_signal(self, kline: KLineData) -> None:
        """执行交易信号"""

        self.signal_price = 0
        position = self.get_position(self.params_map.instrument_id)

        # ========== 平仓逻辑 ==========
        # 如果持有空仓且价格回到中轨，平仓
        # 做空：价格从高位下跌到中轨，所以 close <= middle
        if position.net_position < 0:
            if kline.close <= self.state_map.bb_middle:
                # 价格回到中轨，平空仓（买入）
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

        # ========== 开仓逻辑 ==========
        # 如果处于监听状态
        if self.state_map.monitoring:

            # 检查是否突破上轨+2%
            breakout_price = self.state_map.bb_upper * (1 + self.params_map.breakout_threshold)

            if kline.close > breakout_price:
                # 价格突破上轨+2%，卖出开仓（做空）
                self.signal_price = -kline.close

                if self.trading:
                    order_id = self.send_order(
                        exchange=self.params_map.exchange,
                        instrument_id=self.params_map.instrument_id,
                        volume=self.params_map.order_volume,
                        price=kline.close - self.params_map.pay_up,
                        order_direction="sell"
                    )
                    self.order_id.add(order_id)
                    self.output(f"开空仓: 突破上轨+2%, 开仓价={kline.close}, 上轨={self.state_map.bb_upper}")

                # 开仓后重置监听状态
                self.state_map.monitoring = False
