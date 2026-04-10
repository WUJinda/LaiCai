# encoding: UTF-8

"""
套利合约的下单、合成 K 线

备注：
1. 如果发现 tick 数据和无限易合成的不同, 主要是因为策略运行时间和无限易数据重传时间不同, 而 K 线和 tick 数据最高价和最低价合成方式不同导致的。
2. 本策略仅为 DMA 的交易所标准套利合约使用方法的示例, 作者不对任何收益货损失做保证

last update: 2023年9月27日 13:43:13
"""

import datetime
import gc
import re
import time
from traceback import format_exc, print_exc

import ctaEngine  # type: ignore
from ctaBase import *
from ctaTemplate import (ArrayManager, BarManager, CtaTemplate, KLWidget,
                         StatusCode)
from vtObject import Base, TickData, KLineData


class Demo_DMA_Arbitrage(CtaTemplate):
    """仅供测试_交易所标准套利 DMA 示例"""
    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '标准套利合约',
            'N': '快均线周期',
            'P': '慢均线周期',
            'volume': '下单手数',
            'nMin': 'K线分钟',
            'D': '超价Tick'
        }

        # 变量映射表
        self.varMap = {
            'trading': '交易中',
            'ma0': '慢均线',
            'ma1': '快均线',
            'pos': '持仓'
        }

        # 策略参数
        self.vtSymbol = ''
        self.exchange = ''
        self.N = 5  #: 快均线周期
        self.P = 20  #: 慢均线周期
        self.volume = 1  # 下单手数
        self.nMin = 5
        self.D = 0

        self.widgetClass = KLWidget
        self.widget = None
                
        self.ma0 = 0  # 当前K线慢均线数值
        self.ma1 = 0  # 当前K线快均线数值
        self.ma00 = 0  # 上一个K线慢均线数值
        self.ma10 = 0  # 上一个K线快均线数值

        self.tick1_temp = None
        self.tick2_temp = None

        self.trading = False

        # 启动界面
        self.signal = 0  # 买卖标志
        self.mainSigs = ['ma0', 'ma1']  # 主图显示
        self.subSigs = []  # 副图显示


    # ----------------------------------------------------------------------
    def onTick(self, tick: TickData):
        """收到行情 TICK 推送"""
        if not tick.date:
            tick.date = tick.datetime.strftime('%Y%m%d')

        super().onTick(tick)

        if tick.lastPrice == 0 or tick.askPrice1 == 0 or tick.bidPrice1 == 0:
            return

        if tick.symbol == self.symbol1:
            self.tick1_temp = tick
        elif tick.symbol == self.symbol2:
            self.tick2_temp = tick

        if not all([self.tick1_temp, self.tick2_temp]):
            return

        ticknew = TickDataArbitrage(self.tick1_temp, self.tick2_temp, self.vtSymbol, self.exchange)

        self.bm.updateTick(ticknew)

    # ----------------------------------------------------------------------
    def onBar(self, bar: KLineData):
        """收到Bar推送（必须由用户继承实现）"""
        self.bar = bar
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        # 记录数据
        self.bm.updateBar(bar)

    def onBarX(self, bar: KLineData):
        """收到Bar推送（必须由用户继承实现）"""
        self.bar = bar

        # 记录数据
        if not self.am.updateBar(bar):
            return

        # 计算指标
        self.getCtaIndictor()

        # 计算信号
        self.getCtaSignal(bar)

        # 简易信号执行
        self.execSignal(self.volume)

        # 前收盘
        self.refclose = bar.close

        # 发出状态更新事件
        data = {'bar': self.bar, 'sig': self.signal, 'ma0': self.ma0, 'ma1': self.ma1}
        self.widget.recv_kline(data)

        if self.trading:
            self.putEvent()

    def getCtaIndictor(self):
        """计算指标数据"""
        # 计算指标数值
        ma = self.am.sma(self.P, True)
        ma1 = self.am.sma(self.N, True)
        self.ma0, self.ma00 = ma[-1], ma[-2]
        self.ma1, self.ma10 = ma1[-1], ma1[-2]

    def getCtaSignal(self, bar: KLineData):
        """计算交易信号"""
        close = bar.close
        hour = bar.datetime.hour
        minute = bar.datetime.minute
        # 定义尾盘，尾盘不交易并且空仓
        self.endOfDay = hour == 14 and minute >= 40
        # 判断是否要进行交易
        self.buySig = self.ma1 > self.ma0 and self.ma10 < self.ma00
        self.shortSig = self.ma1 < self.ma0 and self.ma10 > self.ma00
        # 交易价格
        self.longPrice = bar.close
        self.shortPrice = bar.close

    def execSignal(self, volume: int):
        """简易交易信号执行"""
        if not self.trading:
            return

        position = self.get_position(self.vtSymbol)

        # 挂单未成交
        if self.orderID is not None:
            self.cancelOrder(self.orderID)

        self.signal = 0

        if position.net_position == 0 and not self.endOfDay:  #: 当前无仓位
            # 买开，卖开
            if self.shortSig:
                self.signal = -self.shortPrice
                self.orderID = self.short(self.shortPrice - self.D, volume)
                self.output('卖出开仓信号价格：{}'.format(self.shortPrice - self.D))
            elif self.buySig:
                self.signal = self.longPrice
                self.orderID = self.buy(self.longPrice + self.D, volume)
                self.output('买入开仓信号价格：{}'.format(self.longPrice + self.D))

        elif position.net_position > 0 and self.shortSig:  #: 持有多头仓位
            self.signal = -self.shortPrice
            self.orderID = self.auto_close_position(
                price=self.shortPrice - self.D,
                volume=position.net_position,
                symbol=self.vtSymbol,
                exchange=self.exchange,
                order_direction="sell"
            )
            self.output('卖出平仓信号价格：{}'.format(self.shortPrice - self.D))

        elif position.net_position < 0 and self.buySig:  #: 持有空头仓位
            self.signal = self.longPrice
            self.orderID = self.auto_close_position(
                price=self.longPrice + self.D,
                volume=abs(position.net_position),
                symbol=self.vtSymbol,
                exchange=self.exchange,
                order_direction="buy"
            )
            self.output('买入平仓信号价格：{}'.format(self.longPrice + self.D))

    def onInit(self):
        """本策略刚加载的时候不需要显示 QT 界面"""
        super().onInit()
        self.getGui()

    def onTrade(self, trade, log=True):
        super().onTrade(trade, log)

    def onStart(self):
        self.bm = BarManager(self.onBar, self.nMin, self.onBarX)
        self.am = ArrayManager(size=40)
        self.symbol1 = re.findall(r'\s(.+?)&', self.vtSymbol)[0]
        self.symbolList.append(self.symbol1)
        self.exchangeList.append(self.exchange)
        self.symbol2 = re.findall(r'&(.+?)\Z', self.vtSymbol)[0]
        self.symbolList.append(self.symbol2)
        self.exchangeList.append(self.exchange)

        try:
            #: 当从加载实例中启动策略时, K 线图为空, 则需要把 qt_gui 设为 True
            self.loadBarArbitrage(10, qt_gui=True)
        except (TypeError, ValueError) as e:
            self.output(format_exc())
            self.onStop()
            return StatusCode.stop

        self.symExMap = dict([(s, e) for s, e in zip(self.symbolList, self.exchangeList)])

        self.subSymbol()

        self.output('策略启动')
        self.putEvent()

        self.widget.load_data_signal.emit()

    def onStop(self):
        super().onStop()

    def loadBarArbitrage(self, days: int, symbol1=None, symbol2=None, exchange=None, func=None, qt_gui=False) -> None:
        """载入1分钟K线，不大于30天"""
        if qt_gui:
            for _ in range(5):
                #: 如果没有 K 线 UI 没加载全, 会导致线图为空
                if not self.__class__.qtsp:
                    self.output("QT 为空")
                    time.sleep(0.5)

        if days > 30:
            self.output('最多预加载30天的历史1分钟K线数据，请修改参数')
            return

        symbol1 = symbol1 or self.symbol1
        symbol2 = symbol2 or self.symbol2
        exchange = exchange or self.exchange
        func = func or self.onBar

        if not all([symbol1, symbol2, exchange]):
            raise TypeError("错误：交易所或合约为空！")

        # 将天数切割为3天以内的单元
        time_gap = 3
        divisor = int(days / time_gap)
        days_list = [time_gap] * divisor
        if (remainder := days % time_gap) != 0:
            days_list.insert(0, remainder)

        # 分批次把历史数据取到本地，然后统一load
        bars_list = []
        bars_temp = []
        now_time = datetime.datetime.now()
        start_date1 = now_time.strftime('%Y%m%d')
        start_date2 = now_time.strftime('%Y%m%d')
        start_time1 = now_time.strftime("%H:%M:%S")
        start_time2 = now_time.strftime("%H:%M:%S")

        for _days in days_list:
            bars1: list = ctaEngine.getKLineData(symbol1, exchange, start_date1, _days, 0, start_time1, 1)
            bars2: list = ctaEngine.getKLineData(symbol2, exchange, start_date2, _days, 0, start_time2, 1)
            if not bars1:
                raise ValueError(f"错误：请检查参数是否填写正确：[{exchange} {symbol1}]")
            if not bars2:
                raise ValueError(f"错误：请检查参数是否填写正确：[{exchange} {symbol2}]")
            bars1.reverse()
            bars2.reverse()
            bars_list.extend(bars1)
            bars_list.extend(bars2)
            start_date1 = bars1[-1].get('date')
            start_date2 = bars2[-1].get('date')
            start_time1 = bars1[-1].get('time')
            start_time2 = bars2[-1].get('time')

        # 处理数据
        bars_list.sort(key=lambda x: x['datetime'], reverse=True)
        self.bar1_temp = None
        self.bar2_temp = None

        try:
            for _bar in bars_list[::-1]:
                bar_temp = KLineData()
                bar_temp.__dict__.update(_bar)
                if bar_temp.symbol == self.symbol1:
                    self.bar1_temp = bar_temp
                elif bar_temp.symbol == self.symbol2:
                    self.bar2_temp = bar_temp
                if all([self.bar1_temp, self.bar2_temp]):
                    bar = BarDataArbitrage(self.bar1_temp, self.bar2_temp, self.vtSymbol, self.exchange)
                    if bars_temp:
                        if bar.datetime == bars_temp[-1].datetime:
                            bars_temp[-1] = bar
                            continue
                    bars_temp.append(bar)
            for _bar in bars_temp:
                func(_bar)
        except Exception as e:
            print_exc()
            self.output(f'历史数据获取失败，使用实盘数据初始化 {e}')


class BarDataArbitrage(Base):
    """套利K线数据"""

    def __init__(self, bar1, bar2, symbol, exchange):
        """Constructor"""
        super().__init__()
        self.vtSymbol = symbol  # vt系统代码
        self.symbol = symbol  # 代码
        self.exchange = exchange  # 交易所

        self.open = bar1.open - bar2.open  # OHLC
        self.close = bar1.close - bar2.close
        self.high = max(self.open, self.close)  # 因为bar的high和low出现节点不同，不可以直接相减
        self.low = min(self.open, self.close)

        self.date = bar1.date if bar1.date > bar2.date else bar2.date  # bar开始的时间，日期
        self.time = bar1.time if bar1.time > bar2.time else bar2.time  # 时间
        self.datetime = bar1.datetime if bar1.datetime > bar2.datetime else bar2.datetime  # python的datetime时间对象

        self.volume = 0  # 成交量
        self.openInterest = 0  # 持仓量


class TickDataArbitrage(Base):
    """套利tick数据"""

    def __init__(self, tick1=None, tick2=None, symbol=None, exchange=None):
        """Constructor"""
        super().__init__()

        self.vtSymbol = symbol  # vt系统代码
        self.symbol = symbol  # 代码
        self.exchange = exchange  # 交易所

        # 成交数据
        self.lastPrice = tick1.lastPrice - tick2.lastPrice  # 最新成交价
        self.lastVolume = 0  # 最新成交量

        self.volume = 0  # 今天总成交量
        self.openInterest = 0  # 持仓量

        self.date = tick1.date if tick1.date > tick2.date else tick2.date  # bar开始的时间，日期
        self.time = tick1.time if tick1.time > tick2.time else tick2.time  # 时间
        self.datetime = tick1.datetime if tick1.datetime > tick2.datetime else tick2.datetime

        # 常规行情
        self.openPrice = tick1.openPrice - tick2.openPrice  # 今日开盘价
        self.preClosePrice = tick1.preClosePrice - tick2.preClosePrice  # 昨收盘价
        self.highPrice = max(self.openPrice, self.preClosePrice)  # 最高价最低价出现节点不同，不可以直接相减
        self.lowPrice = min(self.openPrice, self.preClosePrice)  # 今日最低价
        self.PreSettlementPrice = tick1.PreSettlementPrice - tick2.PreSettlementPrice  # 昨结算价

        self.upperLimit = tick1.upperLimit - tick2.lowerLimit  # 涨停价
        self.lowerLimit = tick1.lowerLimit - tick2.upperLimit  # 跌停价

        self.turnover = 0.0  # 成交额

        # 五档行情
        self.bidPrice1 = tick1.bidPrice1 - tick2.bidPrice1
        self.bidPrice2 = tick1.bidPrice2 - tick2.bidPrice2
        self.bidPrice3 = tick1.bidPrice3 - tick2.bidPrice3
        self.bidPrice4 = tick1.bidPrice4 - tick2.bidPrice4
        self.bidPrice5 = tick1.bidPrice5 - tick2.bidPrice5

        self.askPrice1 = tick1.askPrice1 - tick2.askPrice1
        self.askPrice2 = tick1.askPrice2 - tick2.askPrice2
        self.askPrice3 = tick1.askPrice3 - tick2.askPrice3
        self.askPrice4 = tick1.askPrice4 - tick2.askPrice4
        self.askPrice5 = tick1.askPrice5 - tick2.askPrice5

        self.bidVolume1 = tick1.bidVolume1 - tick2.bidVolume1
        self.bidVolume2 = tick1.bidVolume2 - tick2.bidVolume2
        self.bidVolume3 = tick1.bidVolume3 - tick2.bidVolume3
        self.bidVolume4 = tick1.bidVolume4 - tick2.bidVolume4
        self.bidVolume5 = tick1.bidVolume5 - tick2.bidVolume5

        self.askVolume1 = tick1.askVolume1 - tick2.askVolume1
        self.askVolume2 = tick1.askVolume2 - tick2.askVolume2
        self.askVolume3 = tick1.askVolume3 - tick2.askVolume3
        self.askVolume4 = tick1.askVolume4 - tick2.askVolume4
        self.askVolume5 = tick1.askVolume5 - tick2.askVolume5 
