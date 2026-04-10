# encoding: UTF-8
"""
last update: 2023年8月20日 17:36:47
"""
from ctaBase import *
from ctaTemplate import CtaTemplate
from vtObject import TickData, TradeData


class Demo_Strategy(CtaTemplate):
    """仅供测试_超过价格发单 (支持多合约)"""

    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '合约',
            'order_price': '买触发价',
            'order_volume': '下单手数'
        }

        # 变量映射表
        self.varMap = {
            'trading': '交易中',
            'pos': '仓位'
        }

        self.vtSymbol = ''
        self.exchange = ''
        self.order_price = 100  # 买入触发价
        self.order_volume = 1  # 下单手数

    def onTick(self, tick: TickData):
        """收到行情 tick 推送"""
        super().onTick(tick)
        # 过滤涨跌停和集合竞价
        if tick.lastPrice == 0 or tick.askPrice1 == 0 or tick.bidPrice1 == 0:
            return
        if tick.lastPrice > self.order_price:
            self.orderID = self.buy_fak(
                price=tick.lowerLimit,
                volume=self.order_volume,
                symbol=tick.symbol,
                exchange=tick.exchange
            )

    def onTrade(self, trade: TradeData):
        super().onTrade(trade, log=True)

    def onStart(self):
        super().onStart()
