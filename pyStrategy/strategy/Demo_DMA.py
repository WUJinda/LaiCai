# encoding: UTF-8

"""
双均线策略
last update: 2023年9月26日 16:27:36
"""

from typing import Dict, List

from ctaTemplate import CtaTemplate, KLWidget
from indicators import Indicators
from utils import MinKLineGenerator
from vtObject import KLineData, TickData


class Demo_DMA(CtaTemplate):
    """仅供测试_可调节 K 线周期的双均线交易策略"""
    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '合约',
            'fast_period': '快均线周期',
            'slow_period': '慢均线周期',
            'order_volume': '下单手数',
            'kline_style': 'K线类型',
            'pay_up': '超价'
        }

        # 变量映射表
        self.varMap = {
            'trading': '交易中',
            'slow_ma': '慢均线',
            'fast_ma': '快均线',
            'pos': '持仓'
        }
        
        self.widgetClass = KLWidget
        self.widget: KLWidget = None
        self.indicators: Indicators = None
        self.kline_generator: MinKLineGenerator = None

        # 策略参数
        self.exchange = ""
        self.vtSymbol = ""
        self.fast_period = 5  # 快均线周期
        self.slow_period = 20  # 慢均线周期
        self.order_volume = 1  # 下单手数
        self.kline_style = "M5" # K 线类型, 具体看 core.pyi 中的 KLineStyle 定义
        self.pay_up = 0 # 超价, 买 + 卖 -

        self.fast_ma = 0  # 当前 K 线快均线数值
        self.slow_ma = 0  # 当前 K 线慢均线数值

        self.pre_fast_ma = 0  # 上一根 K 线快均线数值
        self.pre_slow_ma = 0  # 上一根 K 线慢均线数值

        self.trading = False

        # K 线界面相关
        self.signal = 0  # 买卖标志
        self.subSigs = []

    @property
    def main_indicator(self) -> Dict[str, float]:
        """主图指标"""
        return {
            f"MA{self.fast_period}": self.fast_ma,
            f"MA{self.slow_period}": self.slow_ma
        }

    @property
    def mainSigs(self) -> List[str]:
        """主图显示指标名称"""
        return list(self.main_indicator.keys())

    def onTick(self, tick: TickData) -> None:
        """收到行情 tick 推送"""
        super().onTick(tick)
        
        if tick.lastPrice or tick.askPrice1 or tick.bidPrice1:
            self.kline_generator.tick_to_kline(tick)

    def calc_indicator(self) -> None:
        """计算指标数据"""
        slow_ma = self.indicators.sma(self.slow_period, array=True)
        fast_ma = self.indicators.sma(self.fast_period, array=True)
        self.slow_ma, self.pre_slow_ma = slow_ma[-1], slow_ma[-2]
        self.fast_ma, self.pre_fast_ma = fast_ma[-1], fast_ma[-2]

    def calc_signal(self, kline: KLineData) -> None:
        """计算交易信号"""
        hour = kline.datetime.hour
        minute = kline.datetime.minute
        # 定义尾盘，尾盘不交易并且空仓
        self.end_of_day = hour == 14 and minute >= 40
        # 判断是否要进行交易
        self.buy_signal = self.fast_ma > self.slow_ma and self.pre_fast_ma < self.pre_slow_ma
        self.short_signal = self.fast_ma < self.slow_ma and self.pre_fast_ma > self.pre_slow_ma
        # 交易价格
        self.long_price = kline.close
        self.short_price = kline.close

    def exec_signal(self) -> None:
        """简易交易信号执行"""
        position = self.get_position(self.vtSymbol)

        # 挂单未成交
        if self.orderID is not None:
            self.cancelOrder(self.orderID)

        self.signal = 0

        if position.net_position == 0 and not self.end_of_day:  #: 当前无仓位
            # 买开，卖开
            if self.short_signal:
                self.signal = abs(self.short_price)

                if self.trading is False:
                    return

                self.orderID = self.short(
                    price=(price := self.short_price - self.pay_up),
                    volume=self.order_volume
                )
                self.output(f'卖出开仓信号价格: {price}')

            elif self.buy_signal:
                self.signal = self.long_price

                if self.trading is False:
                    return

                self.orderID = self.buy(
                    price=(price := self.long_price + self.pay_up),
                    volume=self.order_volume
                )
                self.output(f'买入开仓信号价格: {price}')

        elif position.net_position > 0 and self.short_signal:  #: 持有多头仓位
            self.signal = -self.short_price

            if self.trading is False:
                return

            self.orderID = self.auto_close_position(
                price=(price := self.short_price - self.pay_up),
                volume=position.net_position,
                symbol=self.vtSymbol,
                exchange=self.exchange,
                order_direction="sell"
            )
            self.output(f'卖出平仓信号价格: {price}')

        elif position.net_position < 0 and self.buy_signal:  #: 持有空头仓位
            self.signal = self.long_price

            if self.trading is False:
                return

            self.orderID = self.auto_close_position(
                price=(price := self.long_price + self.pay_up),
                volume=abs(position.net_position),
                symbol=self.vtSymbol,
                exchange=self.exchange,
                order_direction="buy"
            )
            self.output(f'买入平仓信号价格: {price}')

    def onInit(self):
        super().onInit()
        self.getGui()

    def onTrade(self, trade, log=True):
        """成交回调"""
        super().onTrade(trade, log)

    def callback(self, kline: KLineData) -> None:
        """接受 K 线回调"""
        self.calc_indicator()

        self.calc_signal(kline)

        self.exec_signal()

        self.putEvent()

        self.widget.recv_kline({
            'bar': kline,
            'sig': self.signal,
            **self.main_indicator
        })

    def real_time_callback(self, kline: KLineData) -> None:
        """使用收到的实时推送 K 线来计算指标并更新线图"""
        self.calc_indicator()

        self.widget.recv_kline({
            'bar': kline,
            'sig': 0,
            **self.main_indicator
        })

    def onStart(self):
        self.kline_generator = MinKLineGenerator(
            real_time_callback=self.real_time_callback,
            callback=self.callback,
            exchange=self.exchange,
            instrument=self.vtSymbol,
            style=self.kline_style
        )

        super().onStart()

    def onStop(self):
        if self.kline_generator:
            self.kline_generator.stop_push_scheduler()

        super().onStop()
