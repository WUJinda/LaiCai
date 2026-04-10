# encoding: UTF-8

"""
肯特纳通道策略
last update: 2023年8月20日 17:36:47
"""

import datetime

from ctaBase import *
from ctaTemplate import ArrayManager, BarManager, CtaTemplate, KLWidget


class Demo_KC(CtaTemplate):
    """仅供测试_技术指标策略模板（肯特纳通道策略）"""
    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'techtype': '技术指标',
            'period': 'K线周期',
            'N': 'KDJ指标参数1',
            'M1': 'KDJ指标参数2',
            'M2': 'KDJ指标参数3',
            'N2': 'ATR指标参数',
            'N1': '快均线周期',
            'P1': '慢均线周期',
            'tradetype': '交易类型',
            'pricetype': '价格优化',
            'volume': '数量',
            'istime': '是否选择时间段',
            'startdt': '开始时间',
            'enddt': '结束时间',
            'istlimit': '是否限制次数',
            'tlimit': '次数限制',
            'exchange': '交易所',
            'vtSymbol': '合约代码',
            'investor': '投资者账号'
        }

        # 变量映射表
        self.varMap = {
            'trading': '交易中',
            'excTimes': '执行次数',
            'pos': '净持仓',
            'macd': '短周期-长周期',
            'signall': 'macd的移动均值',
            'hist': '两值差',
            'bup': '肯特纳上轨',
            'bdn': '肯特纳下轨',
            'ma0': '慢均线',
            'ma1': '快均线',
            'k': 'k值',
            'd': 'd值',
            'j': 'j值',
            'atr': '真实波幅'
        }

        self.techtypes = [
            'keltner',
            'MA',
            'KDJ',
            'ATR',
            'three_black_crows',
            'MACD'
        ]

        self.periods = [
            1,
            5,
            15,
            30,
            60,
            90,
            120
        ]
        self.vtSymbol = ''
        self.exchange = ''
        self.tradetypes = ['B', 'S']
        self.pricetypes = ['D1', 'D2']

        self.widgetClass = KLWidget
        self.widget = None

        # 策略默认参数
        self.techtype = 'keltner'
        self.period = 1
        self.volume = 1
        self.tradetype = 'B'
        self.pricetype = 'D1'
        self.N = 9
        self.N2 = 26
        self.M1 = 3
        self.M2 = 3

        self.istime = False
        self.startdt = '09:00:00'
        self.enddt = '15:00:00'

        self.istlimit = False
        self.tlimit = 10
        # 填写的时候一定要加''，来确保该字段为string,如'119016'
        self.investor = ''

        # 策略状态变量
        self.upPrice = 0  # 涨停价
        self.lowPrice = 0  # 跌停价
        self.askPrice1 = 0  # 卖盘价1
        self.bidPrice1 = 0  # 买盘价1

        self.bup = 0
        self.bdn = 0
        self.refClose = 0
        self.excTimes = 0

        self.buySig = False
        self.sellSig = False
        self.coverSig = False
        self.shortSig = False
        self.Loss = 1  # 止损tick
        self.Profit = 2  # 止盈tick
        self.tick = None
        self.ma0 = 0  # 当前K线慢均线数值
        self.ma1 = 0  # 当前K线快均线数值
        self.ma00 = 0  # 上一个K线慢均线数值
        self.vtTrade = []
        self.ma10 = 0  # 上一个K线快均线数值
        self.k = 0
        self.kk = 0
        self.d = 0
        self.dd = 0
        self.j = 0
        self.jj = 0
        self.P1 = 10
        self.N1 = 5
        self.atr = 0
        self.result = 0
        self.exsig = 0
        self.macd = 0
        self.signall = 0
        self.hist = 0
        self.macd1 = 0
        self.signall1 = 0
        self.hist1 = 0
        self.rsv = []

        self.bm = BarManager(self.onBar, self.period, self.onBarX)
        self.am_day = ArrayManager()
        self.started = False  # 启动
        # 启动界面
        self.cost = 0
        self.signal = 0  # 买卖标志
        self.mainSigs = ['bup', 'bdn', 'ma0', 'ma1']  # 主图显示
        self.subSigs = ['k', 'd', 'j']

        # 注意策略类中的可变对象属性（通常是list和dict等），在策略初始化时需要重新创建，
        # 否则会出现多个策略实例之间数据共享的情况，有可能导致潜在的策略逻辑错误风险，
        # 策略类中的这些可变对象属性可以选择不写，全都放在__init__下面，写主要是为了阅读
        # 策略时方便（更多是个编程习惯的选择）

    def onInit(self):
        """本策略刚加载的时候不需要显示 QT 界面"""
        super().onInit()
        self.getGui()

    def onTick(self, tick):
        """收到行情TICK推送"""
        # 过滤涨跌停和集合竞价
        super().onTick(tick)
        if tick.lastPrice == 0 or tick.askPrice1 == 0 or tick.bidPrice1 == 0:
            return
        self.tick = tick
        self.askPrice1 = tick.askPrice1  # 卖盘价1
        self.bidPrice1 = tick.bidPrice1  # 买盘价1
        self.bm.updateTick(tick)

    def setParam(self, setting):
        """刷新参数"""
        super().setParam(setting)
        self.bm = BarManager(self.onBar, self.period, self.onBarX)
        self.vtSymbol = str(self.vtSymbol)

    def getBBANDS(self):
        if self.tradetype == 'B':
            self.buySig = self.bar.close > self.bar.open and self.bar.close > self.bup
            self.sellSig = self.bar.close < self.bar.open and self.bar.close < self.bdn
        else:
            self.buySig = self.bar.close < self.bar.open and self.bar.close < self.bdn
            self.sellSig = self.bar.close > self.bar.open and self.bar.close > self.bup
        self.shortSig = self.sellSig
        self.coverSig = self.buySig

    def getMA(self):
        if self.tradetype == 'B':
            self.buySig = self.ma1 >= self.ma0 and self.ma10 <= self.ma00
            self.shortSig = self.ma1 <= self.ma0 and self.ma10 >= self.ma00
        else:
            self.buySig = self.ma1 <= self.ma0 and self.ma10 >= self.ma00
            self.shortSig = self.ma1 >= self.ma0 and self.ma10 <= self.ma00
        self.coverSig = self.buySig
        self.sellSig = self.shortSig

    def getKDJ(self):
        if self.tradetype == 'B':
            # 20以内金叉
            self.buySig = 20 >= self.j >= self.k >= self.d and self.jj <= self.kk <= self.dd
            # 80以上死叉
            self.shortSig = 80 <= self.j <= self.k <= self.d and self.jj >= self.kk >= self.dd
        else:
            self.buySig = 80 <= self.j <= self.k <= self.d and self.jj >= self.kk >= self.dd
            self.shortSig = 20 >= self.j >= self.k >= self.d and self.jj <= self.kk <= self.dd
        self.coverSig = self.buySig
        self.sellSig = self.shortSig

    def getATR(self):
        if self.tradetype == 'B':
            self.buySig = self.atr >= 20
            self.shortSig = self.atr < 5
        else:
            self.buySig = self.atr < 5
            self.shortSig = self.atr >= 20
            self.coverSig = self.buySig
            self.sellSig = self.shortSig

    def getThree_black_crows(self):
        # 这个指标需要到 ctaTemplate_option 中去 import
        if self.tradetype == 'B':
            self.buySig = self.result == 100
            self.shortSig = self.result == -100
        else:
            self.buySig = self.result == -100
            self.shortSig = self.result == 100

    def getMACD(self):
        if self.tradetype == 'B':
            # 0位以下金叉
            self.buySig = self.hist <= 0 and self.macd >= self.signall and self.macd1 < self.signall1
            # 0位以下死叉
            self.shortSig = self.hist <= 0 and self.macd <= self.signall and self.macd1 > self.signall1
            # 0位上金叉
            self.sellSig = self.hist >= 0 and self.macd >= self.signall and self.macd1 < self.signall1
            # 0位上死叉
            self.coverSig = self.hist >= 0 and self.macd <= self.signall and self.macd1 > self.signall1

    def onBar(self, bar):
        """收到Bar推送（必须由用户继承实现）"""
        self.bm.updateBar(bar)
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

    def onBarX(self, bar):
        """收到Bar推送（必须由用户继承实现）"""
        self.bar = bar

        # 记录数据
        if not self.am.updateBar(bar):
            return

        # 计算指标
        self.getCtaIndictor(bar)
        self.getCtaIndictor_2(bar)

        # 计算信号
        self.getCtaSignal(bar)

        # 简易信号执行
        self.execSignal(self.volume)

        # 前收盘
        self.refclose = bar.close

        # 发出状态更新事件
        if (not self.widget is None) and (not self.bar is None):
            self.widget.recv_kline({
                'bar': self.bar,
                'sig': self.signal,
                'bup': self.bup,
                'bdn': self.bdn,
                'ma0': self.ma0,
                'ma1': self.ma1,
                'k': self.k,
                'd': self.d,
                'j': self.j,
                'atr': self.atr,
                'tr': self.tr,
                'macd': self.macd,
                'signall': self.signall,
                'hist': self.hist
            })
        if self.trading:
            self.putEvent()

    def getCtaIndictor(self, bar):
        """计算指标数据"""
        # 使用默认参数计算指标数值
        self.bup, self.bdn = self.am.keltner(self.N, 2)
        self.bup, self.bdn = round(self.bup[-1], 2), round(self.bdn[-1], 2)
        ma = self.am.sma(self.P1, True)
        ma1 = self.am.sma(self.N1, True)
        self.ma0, self.ma00 = round(ma[-1], 2), round(ma[-2], 2)
        self.ma1, self.ma10 = round(ma1[-1], 2), round(ma1[-2], 2)

    def getCtaIndictor_2(self, bar):
        """计算指标数据2"""
        K, D, J = self.am.kdj(self.N, self.M1, self.M2, array=True)  # kjd参数设置，一般默认为9，3，3
        self.k, self.d, self.j = round(K[-1], 2), round(D[-1], 2), round(J[-1], 2)
        self.kk, self.dd, self.jj = round(K[-2], 2), round(D[-2], 2), round(J[-2], 2)

        atr_0, tr_0 = self.am.atr(self.N2, array=True)
        self.atr = round(atr_0[-1], 2)
        self.tr = round(tr_0[-1], 2)
        macd, signall, hist = self.am.macdext(12, 26, 9, array=True)
        self.macd, self.signall, self.hist = round(macd[-1], 2), round(signall[-1], 2), round(hist[-1], 2)
        self.macd1, self.signall1, self.hist1 = round(macd[-2], 2), round(signall[-2], 2), round(hist[-2], 2)

    def getCtaSignal(self, bar):
        """计算交易信号"""
        # 定义尾盘，尾盘不交易并且空仓
        self.endOfDay = False

        # 判断是否要进行交易
        if self.techtype == 'keltner':
            self.getBBANDS()
        elif self.techtype == 'MA':
            self.getMA()
        elif self.techtype == 'KDJ':
            self.getKDJ()
        elif self.techtype == 'ATR':
            self.getATR()
        elif self.techtype == 'three_black_crows':
            self.getThree_black_crows()
        elif self.techtype == 'MACD':
            self.getMACD()

        # 计算交易价格
        self.longPrice = bar.close
        self.shortPrice = bar.close
        if self.tick and self.pricetype in self.pricetypes:
            if self.pricetype == 'D1':
                self.longPrice = self.tick.askPrice1
                self.shortPrice = self.tick.bidPrice1
            elif self.pricetype == 'D2':
                self.longPrice = self.tick.askPrice2
                self.shortPrice = self.tick.bidPrice2
        else:
            try:
                self.longPrice = float(self.pricetype)
                self.shortPrice = float(self.pricetype)
            except:
                pass

    def execSignal(self, volume):
        """简易交易信号执行"""
        if self.trading and self.tick is None:
            # 没接到行情
            self.output('行情未初始化')
            return
        elif self.istlimit and self.excTimes > self.tLimit:
            # 次数超限
            self.output('交易次数超限')
            return
        elif self.istime and self.tick and not (self.sTime <= self.tick.datetime.time() <= self.eTime):
            # 时间不满足
            self.output('非交易时间段')
            return
        self.signal = 0

        position = self.get_position(self.vtSymbol)

        if not self.orderID is None:
            # 挂单未成交
            self.cancelOrder(self.orderID)

        if position.net_position > 0:  #: 持有多头仓位,如果正向信号，直接开，如果是反向信号，先平后开
            self.signal = -self.shortPrice
            if self.sellSig:
                self.orderID = self.auto_close_position(
                    price=self.shortPrice,
                    volume=position.net_position,
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    order_direction="sell"
                )
                if self.trading: self.excTimes += 1
            if self.shortSig:
                self.orderID = self.short(self.shortPrice, volume)
                if self.trading: self.excTimes += 1
            if self.buySig:
                self.signal = self.longPrice
                self.orderID = self.buy(self.longPrice, volume)
                if self.trading: self.excTimes += 1
        elif position.net_position < 0:  #: 持有空头仓位,如果正向信号，直接开，如果是反向信号，先平后开
            self.signal = self.longPrice
            if self.coverSig:
                self.orderID = self.auto_close_position(
                    price=self.longPrice,
                    volume=abs(position.net_position),
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    order_direction="buy"
                )
                if self.trading: self.excTimes += 1
            if self.buySig:
                self.orderID = self.buy(self.longPrice, volume)
                if self.trading: self.excTimes += 1
            if self.shortSig:
                self.signal = -self.shortPrice
                self.orderID = self.short(self.shortPrice, volume)
                if self.trading: self.excTimes += 1
        elif position.net_position == 0:  #: 当前无仓位
            # 买开，卖开    
            if self.shortSig:
                self.signal = -self.shortPrice
                self.orderID = self.short(self.shortPrice, volume)
                if self.trading: self.excTimes += 1
            elif self.buySig:
                self.signal = self.longPrice
                self.orderID = self.buy(self.longPrice, volume)
                if self.trading: self.excTimes += 1

    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.bm = BarManager(self.onBar, self.period, self.onBarX)
        self.am = ArrayManager(size=200)

        if str(self.period).isdigit():
            self.loadBar(10)

        self.sTime = datetime.datetime.strptime(self.startdt, '%H:%M:%S').time()
        self.eTime = datetime.datetime.strptime(self.enddt, '%H:%M:%S').time()
        self.excTimes = 0
        self.signal = 0
        self.cost = 0

        self.buySig = False
        self.sellSig = False
        self.coverSig = False
        self.shortSig = False

        self.tick = None

        super().onStart()
        # 查询持仓信息
        self.manage_position()
        self.putEvent()

    def onContractStatus(self, contractStatus):
        super().onContractStatus(contractStatus)
        self.output(contractStatus.status)

    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        # 订单和成本管理
        super().onStop()

    def onTrade(self, trade, log=True):
        super().onTrade(trade, log)
