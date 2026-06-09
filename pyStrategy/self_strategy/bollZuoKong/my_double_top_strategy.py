# ============================================================
# 双峰做空策略 (Double Top Short Strategy)
# ============================================================
# 日线周期做空策略。
# 逻辑：回调到布林中轨 → 回溯30日找左峰 →
#       价格反弹回到左峰区间 → 左侧交易直接做空 → 中轨止盈。
# ============================================================

import numpy as np

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
# 状态码常量
# ============================================================
STATE_IDLE = 0
STATE_WAITING_PULLBACK = 1
STATE_LEFT_PEAK_FOUND = 2
STATE_IN_POSITION = 3


# ============================================================
# 参数类 - 定义策略参数
# ============================================================
class Params(BaseParams):
    """参数映射模型 - 用户可在界面配置"""

    # 基础参数
    exchange: str = Field(default="", title="交易所代码")
    instrument_id: str = Field(default="", title="合约代码")
    kline_style: KLineStyleType = Field(default="D1", title="K线周期")

    # 布林带参数
    bb_period: int = Field(default=20, title="布林带周期", ge=2)
    bb_std: float = Field(default=2.0, title="标准差倍数", ge=0.1)
    bandwidth_min: float = Field(default=0.15, title="最小带宽")

    # 左峰参数
    left_peak_lookback: int = Field(default=30, title="左峰回溯窗口", ge=5)

    # 入场区间参数
    zone_lower: float = Field(default=0.99, title="区间下沿(左峰倍数)")
    zone_upper: float = Field(default=1.02, title="区间上沿(左峰倍数)")

    # 交易参数
    pay_up: int | float = Field(default=0, title="超价")
    margin_rate: float = Field(default=0.10, title="保证金率", ge=0.01, le=1.0)


# ============================================================
# 状态类 - 保存策略运行时的状态
# ============================================================
class State(BaseState):
    """状态映射模型 - 显示在界面上"""

    bb_upper: float = Field(default=0, title="上轨")
    bb_middle: float = Field(default=0, title="中轨")
    bb_lower: float = Field(default=0, title="下轨")
    bandwidth: float = Field(default=0, title="带宽")
    h_left: float = Field(default=0, title="左峰价格")
    zone_lower: float = Field(default=0, title="区间下沿")
    zone_upper: float = Field(default=0, title="区间上沿")
    state_code: int = Field(default=0, title="状态码")


# ============================================================
# 策略主类
# ============================================================
class DoubleTopStrategy(BaseStrategy):
    """双峰做空策略

    日线周期，左侧交易，在价格回到左峰附近时直接做空，
    价格触及布林中轨时平仓止盈。
    """

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

        # ---- 策略内部状态 ----
        self._state: int = STATE_IDLE
        """当前状态码"""

        self._h_left: float = 0.0
        """左峰最高价"""

        self._h_left_idx: int = -1
        """左峰在K线数组中的索引"""

        self._entry_bar_count: int = 0
        """进入 LEFT_PEAK_FOUND 后的K线计数（用于长时间未触发提示）"""

    # ========================================================
    # 主图指标 - 显示在K线图上
    # ========================================================
    @property
    def main_indicator_data(self) -> dict[str, float]:
        """返回主图指标数据"""
        data = {
            "上轨": self.state_map.bb_upper,
            "中轨": self.state_map.bb_middle,
            "下轨": self.state_map.bb_lower,
        }
        if self._h_left > 0:
            data["左峰(H_left)"] = self._h_left
            data["区间下沿"] = self.state_map.zone_lower
            data["区间上沿"] = self.state_map.zone_upper
        return data

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
        """日K线完成时回调 — 指标计算 + 状态机 + 交易执行"""

        # 1. 撤销上一根K线未成交的挂单
        if len(self.order_id) > 0:
            for order_id in list(self.order_id):
                self.cancel_order(order_id)

        # 2. 计算布林带指标
        self.calc_indicator()

        # 3. 获取持仓状态
        position = self.get_position(self.params_map.instrument_id)
        has_pending = len(self.order_id) > 0

        self.signal_price = 0

        # 4. 状态同步：如果之前是持仓状态但实际已无仓位且无挂单 → 重置
        if self._state == STATE_IN_POSITION and position.net_position == 0 and not has_pending:
            self.output("状态同步: 持仓已平，重置到IDLE")
            self._reset()

        # 5. 持仓中 + 无挂单 → 检查止盈
        if position.net_position < 0 and not has_pending:
            if kline.close <= self.state_map.bb_middle:
                self.signal_price = kline.close
                if self.trading:
                    self._close_position(position)
                self.output(
                    f"平空仓止盈: 价格回到中轨, "
                    f"平仓价={kline.close:.2f}, 中轨={self.state_map.bb_middle:.2f}"
                )
                self._reset()

        # 6. 空仓 + 无挂单 → 状态机流转（可能入场）
        elif position.net_position == 0 and not has_pending:
            self.update_state_machine(kline)

        # 7. 更新图表
        self.widget.recv_kline({
            "kline": kline,
            "signal_price": self.signal_price,
            **self.main_indicator_data
        })

    def real_time_callback(self, kline: KLineData) -> None:
        """实时tick回调 — 仅更新图表，交易在callback中执行"""

        # 更新指标（当前未完成K线的最新值）
        self.calc_indicator()

        # 更新图表
        self.widget.recv_kline({
            "kline": kline,
            "signal_price": self.signal_price,
            **self.main_indicator_data
        })

    # ========================================================
    # 指标计算
    # ========================================================
    def calc_indicator(self) -> None:
        """计算布林带指标和带宽"""
        producer = self.kline_generator.producer

        bb_middle = float(producer.sma(self.params_map.bb_period))
        bb_upper, bb_lower = producer.boll(
            timeperiod=self.params_map.bb_period,
            deviation=int(self.params_map.bb_std)
        )
        bb_upper = float(bb_upper)
        bb_lower = float(bb_lower)

        self.state_map.bb_upper = bb_upper
        self.state_map.bb_middle = bb_middle
        self.state_map.bb_lower = bb_lower

        if self.state_map.bb_middle > 0:
            self.state_map.bandwidth = (
                (self.state_map.bb_upper - self.state_map.bb_lower)
                / self.state_map.bb_middle
            )

        # 更新区间显示
        if self._h_left > 0:
            self.state_map.h_left = self._h_left
            self.state_map.zone_lower = self._h_left * self.params_map.zone_lower
            self.state_map.zone_upper = self._h_left * self.params_map.zone_upper

    # ========================================================
    # 状态机
    # ========================================================
    def update_state_machine(self, kline: KLineData) -> None:
        """状态机主逻辑

        状态转换:
          IDLE → WAITING_PULLBACK (带宽达标)
          WAITING_PULLBACK → LEFT_PEAK_FOUND (价格≤中轨, 找左峰)
          LEFT_PEAK_FOUND → IN_POSITION   (价格进入区间, 立即做空)
          LEFT_PEAK_FOUND → IDLE          (价格突破区间上沿)
        """
        close = kline.close

        # ---- IDLE: 等待带宽达标 ----
        if self._state == STATE_IDLE:
            if self._check_data_ready() and self._check_bandwidth():
                self._set_state(STATE_WAITING_PULLBACK)
                self.output(
                    f"进入监控: 带宽={self.state_map.bandwidth:.4f} > "
                    f"阈值{self.params_map.bandwidth_min}"
                )

        # ---- WAITING_PULLBACK: 等待价格回落到中轨 ----
        # 注意: 用 if 而非 elif，允许同一根K线内完成 IDLE→WAITING_PULLBACK→LEFT_PEAK_FOUND
        if self._state == STATE_WAITING_PULLBACK:
            if close <= self.state_map.bb_middle:
                self._find_left_peak()
                self._set_state(STATE_LEFT_PEAK_FOUND)
                self._entry_bar_count = 0
                self.output(
                    f"左峰确认: H_left={self._h_left:.2f}, "
                    f"中轨={self.state_map.bb_middle:.2f}, "
                    f"区间=[{self.state_map.zone_lower:.2f}, {self.state_map.zone_upper:.2f}]"
                )

        # ---- LEFT_PEAK_FOUND: 等待价格回到左峰区间 ----
        elif self._state == STATE_LEFT_PEAK_FOUND:
            self._entry_bar_count += 1

            # 超时退出：等待超过回溯窗口仍未进入区间 → 形态失效
            if self._entry_bar_count > self.params_map.left_peak_lookback:
                self.output(
                    f"形态超时: 等待{self._entry_bar_count}根K线未进入区间, "
                    f"重置"
                )
                self._reset()
                return

            # 价格突破区间上沿 → 形态失效
            if close > self._h_left * self.params_map.zone_upper:
                self.output(
                    f"形态失效: 价格突破区间上沿, "
                    f"close={close:.2f} > {self._h_left * self.params_map.zone_upper:.2f}"
                )
                self._reset()
                return

            # 价格进入区间 → 左侧交易，立即做空
            if self._in_zone(close):
                self._execute_short(kline)
                self._set_state(STATE_IN_POSITION)

        # ---- IN_POSITION: 等待止盈（在 callback 中检查） ----
        elif self._state == STATE_IN_POSITION:
            # 交易执行在 callback 主循环中处理（检查 net_position）
            pass

    # ========================================================
    # 辅助方法
    # ========================================================
    def _check_data_ready(self) -> bool:
        """检查是否有足够的历史数据"""
        producer = self.kline_generator.producer
        if producer is None:
            return False
        return len(producer.close) >= self.params_map.left_peak_lookback

    def _check_bandwidth(self) -> bool:
        """检查带宽是否达标（> bandwidth_min）"""
        return self.state_map.bandwidth > self.params_map.bandwidth_min

    def _find_left_peak(self) -> None:
        """在回调到中轨时，向前回溯找左峰（30日最高价）"""
        producer = self.kline_generator.producer
        highs = producer.high
        lookback = self.params_map.left_peak_lookback

        if len(highs) < lookback:
            return

        # 取最近 lookback 根K线的最高价及其索引
        recent_highs = highs[-lookback:]
        max_idx_in_window = int(np.argmax(recent_highs))
        self._h_left = float(recent_highs[max_idx_in_window])
        self._h_left_idx = len(highs) - lookback + max_idx_in_window

        # 同步到状态显示
        self.state_map.h_left = self._h_left
        self.state_map.zone_lower = self._h_left * self.params_map.zone_lower
        self.state_map.zone_upper = self._h_left * self.params_map.zone_upper

    def _in_zone(self, price: float) -> bool:
        """判断价格是否在入场区间内"""
        if self._h_left <= 0:
            return False
        lower = self._h_left * self.params_map.zone_lower
        upper = self._h_left * self.params_map.zone_upper
        return lower <= price <= upper

    def _set_state(self, new_state: int) -> None:
        """更新状态码并同步到界面"""
        self._state = new_state
        self.state_map.state_code = new_state

    def _reset(self) -> None:
        """重置策略内部状态（回到IDLE）"""
        self._set_state(STATE_IDLE)
        self._h_left = 0.0
        self._h_left_idx = -1
        self._entry_bar_count = 0
        self.state_map.h_left = 0
        self.state_map.zone_lower = 0
        self.state_map.zone_upper = 0

    # ========================================================
    # 交易执行
    # ========================================================
    def _execute_short(self, kline: KLineData) -> None:
        """执行做空入场"""
        self.signal_price = -kline.close

        if not self.trading:
            self.output(
                f"[模拟] 做空信号: H_left={self._h_left:.2f}, "
                f"入场价={kline.close:.2f}, 区间=[{self.state_map.zone_lower:.2f}, "
                f"{self.state_map.zone_upper:.2f}]"
            )
            return

        volume = self.calc_volume(kline.close)
        if volume <= 0:
            self.output("手数计算为0，无法开仓")
            return

        order_id = self.send_order(
            exchange=self.params_map.exchange,
            instrument_id=self.params_map.instrument_id,
            volume=volume,
            price=kline.close - self.params_map.pay_up,
            order_direction="sell"
        )
        if order_id is not None:
            self.order_id.add(order_id)
        else:
            self.output("❌ 开空仓失败: send_order 返回 None")

        self.output(
            f"开空仓: 价格进入双峰区间, "
            f"H_left={self._h_left:.2f}, "
            f"入场价={kline.close:.2f}, "
            f"区间=[{self.state_map.zone_lower:.2f}, {self.state_map.zone_upper:.2f}], "
            f"手数={volume}"
        )

    def _close_position(self, position) -> None:
        """平空仓止盈"""
        order_id = self.auto_close_position(
            exchange=self.params_map.exchange,
            instrument_id=self.params_map.instrument_id,
            volume=abs(position.net_position),
            price=self.state_map.bb_middle + self.params_map.pay_up,
            order_direction="buy"
        )
        if order_id is not None:
            self.order_id.add(order_id)
        else:
            self.output("❌ 平仓失败: auto_close_position 返回 None")

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

        return max(volume, 0)
