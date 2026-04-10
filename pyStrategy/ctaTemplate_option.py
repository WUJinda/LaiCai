'''
本文件包含了CTA引擎中策略开发用模板(目前支持多合约)
last update: 2022-09-19 11:05:19
'''
import csv
import datetime
import gc
import json
import os
from collections import OrderedDict

import ctaEngine
import numpy as np
import scipy.linalg as slin
import scipy.optimize as opt
import scipy.stats as sps
import talib

from ctaBase import *
from vtConstant import *
from vtObject import *


class CtaTemplate_option(object):
    """CTA策略模板"""

    # 策略类的名称和作者
    author = EMPTY_UNICODE
    className = 'CtaTemplate_option'

    # MongoDB数据库的名称，K线数据库默认为1分钟
    tickDbName = TICK_DB_NAME
    barDbName = MINUTE_DB_NAME

    t = None
    qtsp = None

    # 策略的基本参数
    name = EMPTY_UNICODE  # 策略实例名称
    vtSymbol = EMPTY_STRING  # 交易的合约vt系统代码
    symbolList = []  # 所有需要订阅的合约
    exchangeList = []  # 所有需要订阅合约的交易所
    crossSize = {}  # 盘口撮合量

    # 无限易客户端相关变量
    exchange = EMPTY_STRING  # 交易的合约vt系统代码
    paramMap = {}  # 参数显示映射表
    varMap = {}  # 变量显示映射表

    # 策略的基本变量，由引擎管理
    inited = False  # 是否进行了初始化
    trading = False  # 是否启动交易，由引擎管理
    backtesting = False  # 回测模式

    # 策略内部管理的仓位
    pos = {}  # 总投机方向
    tpos0L = {}  # 今持多仓
    tpos0S = {}  # 今持空仓
    ypos0L = {}  # 昨持多仓
    ypos0S = {}  # 昨持空仓

    baseparamList = [
        'name',
        'author',
        'className',
        'vtSymbol',
        'exchange',
        'investor'
    ]

    # 变量列表，保存了变量的名称
    basevarList = [
        'inited',
        'trading',
        'pos'
    ]

    ctaEngine.writeLog("此类即将弃用，请更换 option_template.py 使用")

    # ----------------------------------------------------------------------
    def __init__(self, ctaEngine, setting):
        """Constructor"""
        self.ctaEngine = ctaEngine

        # 无限易客户端需要
        self.sid = 0  # 策略ID
        self.vtSymbol = EMPTY_STRING  # 合约
        self.exchange = EMPTY_STRING  # 交易的合约vt系统代码
        self.investor = EMPTY_STRING
        self.volume = EMPTY_INT
        # 策略的基本变量，由引擎管理
        self.inited = False  # 是否进行了初始化
        self.trading = False  # 是否启动交易，由引擎管理
        self.backtesting = False  # 回测模式

        self.bar = None  # K线对象
        self.barMinute = EMPTY_INT  # K线当前的分钟

        self.orderID = None  # 上一笔订单
        self.tradeDate = None  # 当前交易日

        # 仓位信息
        self.pos = {}  # 总投机方向
        self.tpos0L = {}  # 今持多仓
        self.tpos0S = {}  # 今持空仓
        self.ypos0L = {}  # 昨持多仓
        self.ypos0S = {}  # 昨持空仓

        # 定义尾盘，判断是否要进行交易
        self.endOfDay = False
        self.buySig = False
        self.shortSig = False
        self.coverSig = False
        self.sellSig = False

        # 默认交易价格
        self.longPrice = EMPTY_FLOAT  # 多头开仓价
        self.shortPrice = EMPTY_FLOAT  # 空头开仓价

        # 默认技术指标列表
        self.am = ArrayManager(size=100)

        # 回测需要
        self.crossSize = {}  # 盘口撮合量

        self.symbolList = []  # 所有需要订阅的合约
        self.exchangeList = []  # 所有需要订阅合约的交易所
        self.symExMap = {}

        # 参数和状态
        self.varList = self.basevarList + self.varList
        self.paramList = self.baseparamList + self.paramList

        # 设置策略的参数
        self.onUpdate(setting)

        # 用于界面显示的映射表
        if not self.paramMap:
            self.paramMap = dict(zip(self.paramList, self.paramList))
        if not self.varMap:
            self.varMap = dict(zip(self.varList, self.varList))
        self.paramMapReverse = {v: k for k, v in self.paramMap.items()}
        self.varMapReverse = {v: k for k, v in self.varMap.items()}

        self.widget = None
        self.paramLoaded = False

    # ----------------------------------------------------------------------
    def onUpdate(self, setting):
        """刷新策略"""
        # 按输入字典更新
        if setting:
            d = self.__dict__
            for key in self.paramList:
                if key in setting:
                    d[key] = setting[key]

        self.vtSymbol = str(self.vtSymbol)
        self.exchange = str(self.exchange)

        # 所有需要订阅的合约
        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')
        self.symExMap = dict([(s, e) for s, e in zip(self.symbolList, self.exchangeList)])

        # 初始化仓位信息
        self.pos = {}  # 总投机方向
        self.tpos0L = {}  # 今持多仓
        self.tpos0S = {}  # 今持空仓
        self.ypos0L = {}  # 昨持多仓
        self.ypos0S = {}  # 昨持空仓
        for symbol in self.symbolList:
            self.pos[symbol] = 0
            self.ypos0L[symbol] = 0
            self.tpos0L[symbol] = 0
            self.ypos0S[symbol] = 0
            self.tpos0S[symbol] = 0

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    def subSymbol(self):
        """重新订阅合约"""
        for symbol, exchange in zip(self.symbolList, self.exchangeList):
            ctaEngine.subMarketData(
                {'sid': self,
                 'InstrumentID': str(symbol),
                 'ExchangeID': str(exchange)})

    # ----------------------------------------------------------------------
    def unSubSymbol(self):
        """取消订阅合约"""
        for symbol, exchange in zip(self.symbolList, self.exchangeList):
            ctaEngine.unsubMarketData(
                {'sid': self,
                 'InstrumentID': str(symbol),
                 'ExchangeID': str(exchange)})

    # ----------------------------------------------------------------------
    def setParam(self, setting):
        """刷新参数"""
        updateSymbol = False
        if setting:
            d = self.__dict__
            param = {"sid": self.sid}
            for key in self.paramList:
                if key in self.paramMap:
                    strgbk = self.paramMap[key]
                    if strgbk in setting:
                        param[strgbk.encode('gbk')] = setting[strgbk]
                        # 修改合约参数就重新订阅
                        if key == 'vtSymbol':
                            d[key] = setting[strgbk]
                        elif key == 'exchange':
                            d[key] = setting[strgbk]
                        else:
                            try:
                                d[key] = eval(setting[strgbk])
                            except:
                                d[key] = setting[strgbk]

        # 初始化仓位信息
        self.symbolList = d['vtSymbol'].split(';')
        self.exchangeList = d['exchange'].split(';')
        self.pos = {}
        self.tpos0L = {}
        self.tpos0S = {}
        self.ypos0L = {}
        self.ypos0S = {}
        for symbol in self.symbolList:
            self.pos[symbol] = 0
            self.ypos0L[symbol] = 0
            self.tpos0L[symbol] = 0
            self.ypos0S[symbol] = 0
            self.tpos0S[symbol] = 0
        ctaEngine.updateParam(param)
        self.putEvent()

    # ----------------------------------------------------------------------
    def getParam(self):
        """获取参数，没看到使用"""
        setting = OrderedDict()
        for key in reversed(self.paramList):
            if key in self.paramMap:
                setting[self.paramMap[key]] = str(getattr(self, key))
        return setting

    # ----------------------------------------------------------------------
    def getParamOrgin(self):
        """获取参数,onStop时调用"""
        setting = {}
        for key in reversed(self.paramList):
            setting[key] = getattr(self, key)
        return setting

    # ----------------------------------------------------------------------
    def getVar(self):
        """获取变量，没看到使用"""
        setting = OrderedDict()
        d = self.__dict__
        for key in self.varList:
            setting[key] = str(d[key])
        return setting

    # ----------------------------------------------------------------------
    def onInit(self):
        """初始化策略（必须由用户继承实现）"""
        try:
            if not self.paramLoaded:
                self.paramLoaded = True
                path = os.path.split(os.path.realpath(__file__))[0] + '\\json\\'
                with open(path + self.name + '.json') as f:
                    setting = json.loads(f.read())
                    self.onUpdate(setting)
                self.output(u'使用保存参数')
        except:
            pass
        self.output(u'%s策略初始化' % self.name)
        self.inited = True
        self.putEvent()

    # ----------------------------------------------------------------------
    def onStart(self):
        """启动策略（必须由用户继承实现）"""
        self.trading = True

        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')
        self.symExMap = dict([(s, e) for s, e in zip(self.symbolList, self.exchangeList)])

        self.subSymbol()
        self.output(u'%s策略启动' % self.name)
        self.putEvent()
        if self.widget is not None and self.bar is not None:
            self.widget.signalLoad.emit()

    def manage_position(self, is_separate=False, index=1):
        """仓位处理"""
        if not is_separate:
            pos_list = self.getInvestorPosition(self.get_investor(index))
            # 获取第一个投资者账号
            for symbol in self.symbolList:
                self.pos[symbol] = 0
            for pos in pos_list:
                if pos['InstrumentID'] in self.symbolList:
                    if pos['Direction'] == u'多':
                        self.pos[pos['InstrumentID']] += pos['Position']
                        # 昨持多仓
                        self.ypos0L[pos['InstrumentID']] = pos['YdPositionClose']
                        # 今持多仓
                        self.tpos0L[pos['InstrumentID']] = pos['Position'] - pos['YdPositionClose']
                    elif pos['Direction'] == u'空':
                        self.pos[pos['InstrumentID']] -= pos['Position']
                        # 昨持空仓
                        self.ypos0S[pos['InstrumentID']] = pos['YdPositionClose']
                        # 今持空仓
                        self.tpos0S[pos['InstrumentID']] = pos['Position'] - pos['YdPositionClose']

    def onStop(self):
        """停止策略（必须由用户继承实现）"""
        self.unSubSymbol()  # 断开合约订阅
        self.output(u'%s策略停止' % self.name)
        setting = self.getParamOrgin()
        try:
            path = os.path.split(os.path.realpath(__file__))[0] + '\\json\\'
            with open(path + self.name + '.json', 'w') as f:
                f.write(json.dumps(setting))
            self.output(u'保存策略参数')
        except:
            self.output(traceback.format_exc())
        if self.widget is not None:
            self.widget.clear()
        self.trading = False
        self.putEvent()

    # ----------------------------------------------------------------------
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""
        # 判断交易日更新
        if self.tradeDate is None:
            self.tradeDate = tick.date
        elif not self.tradeDate == tick.date:
            self.output(u'当前交易日 ：' + tick.date)
            self.tradeDate = tick.date
            for symbol in self.symbolList:
                self.ypos0L[symbol] += self.tpos0L[symbol]
                self.tpos0L[symbol] = 0
                self.ypos0S[symbol] += self.tpos0S[symbol]
                self.tpos0S[symbol] = 0

    # ----------------------------------------------------------------------
    def onOrderCancel(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        self.orderID = None

    # ----------------------------------------------------------------------
    def onOrderTrade(self, order):
        """收到委托变化推送（必须由用户继承实现）"""
        self.orderID = None

    # ----------------------------------------------------------------------
    def onOrder(self, order, log=False):
        """收到委托变化推送（必须由用户继承实现）"""
        if order is None:
            return
        # 对于无需做细粒度委托控制的策略，可以忽略onOrder
        # CTA委托  类型映射
        offset = order.offset
        status = order.status
        if status == u'已撤销':
            self.onOrderCancel(order)
        elif status == u'全部成交' or status == u'部成部撤':
            self.onOrderTrade(order)
        if log:
            self.output(' '.join([offset, status]))
            self.output('')

    # ----------------------------------------------------------------------
    def onErr(self, error):
        """收到错误推送（必须由用户继承实现）"""
        if 'errCode' in error:
            errCode = error['errCode']
            self.writeCtaLog(errCode)
        if 'errMsg' in error:
            errMsg = error['errMsg']
            self.writeCtaLog(errMsg)

    # ----------------------------------------------------------------------
    def onTimer(self, tid):
        """收到定时推送"""
        pass

    # ----------------------------------------------------------------------
    def onTrade(self, trade, log=False):
        """收到成交推送（必须由用户继承实现）"""
        if trade is None:
            return
        price = trade.price
        volume = trade.volume
        symbol = trade.vtSymbol
        offset = trade.offset
        direction = trade.direction
        if direction == u'多':
            self.pos[symbol] += volume
            if offset == u'开仓':
                self.tpos0L[symbol] += volume
            elif offset == u'平今':
                self.tpos0S[symbol] -= volume
            elif offset == u'平仓' or offset == u'平昨':
                self.ypos0S[symbol] -= volume
        elif direction == u'空':
            self.pos[symbol] -= volume
            if offset == u'开仓':
                self.tpos0S[symbol] += volume
            elif offset == u'平仓' or offset == u'平昨':
                self.ypos0L[symbol] -= volume
            elif offset == u'平今':
                self.tpos0L[symbol] -= volume
        if log:
            self.output(trade.tradeTime
                        + u' 合约:' + str(symbol)
                        + u'|{}{}成交:'.format(direction, offset) + str(price)
                        + u'|手数:' + str(volume))
        self.output(u' ')
        gc.collect()

    # ----------------------------------------------------------------------
    def getCtaIndicator(self, bar):
        pass

    def getCtaSignal(self, bar):
        pass

    def onBar(self, bar):
        """收到Bar推送（必须由用户继承实现）"""
        self.bar = bar
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        # 记录数据
        if not self.am.updateBar(bar):
            return

        # 计算指标
        self.getCtaIndicator(bar)

        # 计算信号
        self.getCtaSignal(bar)

        # 简易信号执行
        self.execSignal(self.volume)

        # 发出状态更新事件
        self.putEvent()

    # ----------------------------------------------------------------------
    def onXminBar(self, bar):
        """收到Bar推送（必须由用户继承实现）"""
        self.bar = bar
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        # 记录数据
        if not self.am.updateBar(bar):
            return

        # 计算指标
        self.getCtaIndicator(bar)

        # 计算信号
        self.getCtaSignal(bar)

        # 简易信号执行
        self.execSignal(self.volume)

        # 发出状态更新事件
        self.putEvent()

    # ----------------------------------------------------------------------
    def execSignal(self, volume):
        """简易交易信号执行"""
        pos = self.pos[self.vtSymbol]
        endOfDay = self.endOfDay
        # 挂单未成交
        if not self.orderID is None:
            self.cancelOrder(self.orderID)

        # 当前无仓位
        if pos == 0 and not self.endOfDay:
            # 买开，卖开    
            if self.shortSig:
                self.orderID = self.short(self.shortPrice, volume)
            elif self.buySig:
                self.orderID = self.buy(self.longPrice, volume)

        # 持有多头仓位
        elif pos > 0 and (self.sellSig or self.endOfDay):
            self.orderID = self.sell(self.shortPrice, pos)

        # 持有空头仓位
        elif pos < 0 and (self.coverSig or self.endOfDay):
            self.orderID = self.cover(self.longPrice, -pos)

    # ----------------------------------------------------------------------
    def sell_y(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_SELL, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def sell_t(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def buy(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_BUY, price, volume, symbol, exchange, investor)

    # ----------------------------------------------------------------------
    def short(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_SHORT, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def sell(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0L = self.tpos0L.get(symbol)
        ypos0L = self.ypos0L.get(symbol)
        if tpos0L >= volume:
            return self.sendOrder(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0L >= volume:
            return self.sendOrder(CTAORDER_SELL, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def cover(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0S = self.tpos0S.get(symbol)
        ypos0S = self.ypos0S.get(symbol)
        if tpos0S >= volume:
            return self.sendOrder(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0S >= volume:
            return self.sendOrder(CTAORDER_COVER, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def cover_y(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_COVER, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def cover_t(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrder(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def buy_fok(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrderFOK(CTAORDER_BUY, price, volume, symbol, exchange, investor)

    # ----------------------------------------------------------------------
    def sell_fok(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0L = self.tpos0L.get(symbol)
        ypos0L = self.ypos0L.get(symbol)
        if tpos0L >= volume:
            return self.sendOrderFOK(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0L >= volume:
            return self.sendOrderFOK(CTAORDER_SELL, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def short_fok(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrderFOK(CTAORDER_SHORT, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def cover_fok(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0S = self.tpos0S.get(symbol)
        ypos0S = self.ypos0S.get(symbol)
        if tpos0S >= volume:
            return self.sendOrderFOK(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0S >= volume:
            return self.sendOrderFOK(CTAORDER_COVER, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def buy_fak(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrderFAK(CTAORDER_BUY, price, volume, symbol, exchange, investor)

    # ----------------------------------------------------------------------
    def sell_fak(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0L = self.tpos0L.get(symbol)
        ypos0L = self.ypos0L.get(symbol)
        if tpos0L >= volume:
            return self.sendOrderFAK(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0L >= volume:
            return self.sendOrderFAK(CTAORDER_SELL, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def short_fak(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """卖开"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        return self.sendOrderFAK(CTAORDER_SHORT, price, volume, symbol, exchange, investor)

        # ----------------------------------------------------------------------

    def cover_fak(self, price, volume, symbol='', exchange='', stop=False, investor=''):
        """买平"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0S = self.tpos0S.get(symbol)
        ypos0S = self.ypos0S.get(symbol)
        if tpos0S >= volume:
            return self.sendOrderFAK(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor)
        elif ypos0S >= volume:
            return self.sendOrderFAK(CTAORDER_COVER, price, volume, symbol, exchange, investor)

            # ----------------------------------------------------------------------

    def close(self, price, symbol='', exchange='', stop=False, investor=''):
        """自动全平：参数必须完整"""
        symbol = self.symbolList[0] if symbol == '' else symbol
        exchange = self.symExMap.get(symbol, '') if exchange == '' else exchange
        tpos0L = self.tpos0L[symbol]  # 今持多仓
        ypos0L = self.ypos0L[symbol]  # 昨持多仓
        tpos0S = self.tpos0S[symbol]  # 今持空仓
        ypos0S = self.ypos0S[symbol]  # 昨持空仓
        if exchange == 'SHFE' or exchange == 'INE':
            if tpos0L > 0 and ypos0L > 0 and tpos0S == 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor)
            elif tpos0L > 0 and ypos0L > 0 and tpos0S > 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L > 0 and ypos0L > 0 and tpos0S == 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L > 0 and ypos0L > 0 and tpos0S > 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor)
            elif tpos0L > 0 and ypos0L == 0 and tpos0S > 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L > 0 and tpos0S > 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L == 0 and tpos0S > 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L == 0 and tpos0S == 0 and ypos0S > 0:
                return self.sendOrder(CTAORDER_COVER, price, ypos0S, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L == 0 and tpos0S > 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor)
            elif tpos0L > 0 and ypos0L == 0 and tpos0S == 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL_TODAY, price, tpos0L, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L > 0 and tpos0S == 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor)
            elif tpos0L == 0 and ypos0L > 0 and tpos0S > 0 and ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL, price, ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER_TODAY, price, tpos0S, symbol, exchange, investor)
            else:
                pass
        elif exchange != 'SHFE' and exchange != 'INE':
            if tpos0L + ypos0L > 0 and tpos0S + ypos0S == 0:
                return self.sendOrder(CTAORDER_SELL, price, tpos0L + ypos0L, symbol, exchange, investor)

            elif tpos0L + ypos0L > 0 and tpos0S + ypos0S > 0:
                return self.sendOrder(CTAORDER_SELL, price, tpos0L + ypos0L, symbol, exchange, investor), \
                       self.sendOrder(CTAORDER_COVER, price, tpos0S + ypos0S, symbol, exchange, investor)
            elif tpos0L + ypos0L == 0 and tpos0S + ypos0S > 0:
                return self.sendOrder(CTAORDER_COVER, price, tpos0S + ypos0S, symbol, exchange, investor)
        else:
            pass
            # ----------------------------------------------------------------------

    def sendOrder(self, orderType, price, volume, symbol, exchange, investor='', stop=False):
        """发送委托"""
        if self.trading:
            # 如果stop为True，则意味着发本地停止单
            req = {}
            req['sid'] = self.sid
            if orderType == CTAORDER_BUY:
                req['direction'] = '0'
                req['offset'] = '0'
            elif orderType == CTAORDER_SELL:
                req['direction'] = '1'
                req['offset'] = '1'
            elif orderType == CTAORDER_SELL_TODAY:
                req['direction'] = '1'
                req['offset'] = '3'
            elif orderType == CTAORDER_SHORT:
                req['direction'] = '1'
                req['offset'] = '0'
            elif orderType == CTAORDER_COVER:
                req['direction'] = '0'
                req['offset'] = '1'
            elif orderType == CTAORDER_COVER_TODAY:
                req['direction'] = '0'
                req['offset'] = '3'
            req['symbol'] = symbol
            req['volume'] = volume
            req['price'] = price
            req['hedgeflag'] = '1'
            req['ordertype'] = '0'
            req['exchange'] = exchange
            req['investor'] = investor
            vtOrderID = ctaEngine.sendOrder(req)
            return vtOrderID
        else:
            return None

            # ----------------------------------------------------------------------

    def sendOrderFOK(self, orderType, price, volume, symbol, exchange, investor='', stop=False):
        """发送委托"""
        if self.trading:
            # 如果stop为True，则意味着发本地停止单
            req = {}
            req['sid'] = self.sid
            if orderType == CTAORDER_BUY:
                req['direction'] = '0'
                req['offset'] = '0'
            elif orderType == CTAORDER_SELL:
                req['direction'] = '1'
                req['offset'] = '1'
            elif orderType == CTAORDER_SELL_TODAY:
                req['direction'] = '1'
                req['offset'] = '3'
            elif orderType == CTAORDER_SHORT:
                req['direction'] = '1'
                req['offset'] = '0'
            elif orderType == CTAORDER_COVER:
                req['direction'] = '0'
                req['offset'] = '1'
            elif orderType == CTAORDER_COVER_TODAY:
                req['direction'] = '0'
                req['offset'] = '3'
            req['symbol'] = symbol
            req['volume'] = volume
            req['price'] = price
            req['hedgeflag'] = '1'
            req['ordertype'] = '2'
            req['exchange'] = exchange
            req['investor'] = investor
            vtOrderID = ctaEngine.sendOrder(req)
            return vtOrderID
        else:
            return None

            # ----------------------------------------------------------------------

    def sendOrderFAK(self, orderType, price, volume, symbol, exchange, investor='', stop=False):
        """发送委托"""
        if self.trading:
            # 如果stop为True，则意味着发本地停止单
            req = {}
            req['sid'] = self.sid
            if orderType == CTAORDER_BUY:
                req['direction'] = '0'
                req['offset'] = '0'
            elif orderType == CTAORDER_SELL:
                req['direction'] = '1'
                req['offset'] = '1'
            elif orderType == CTAORDER_SELL_TODAY:
                req['direction'] = '1'
                req['offset'] = '3'
            elif orderType == CTAORDER_SHORT:
                req['direction'] = '1'
                req['offset'] = '0'
            elif orderType == CTAORDER_COVER:
                req['direction'] = '0'
                req['offset'] = '1'
            elif orderType == CTAORDER_COVER_TODAY:
                req['direction'] = '0'
                req['offset'] = '3'
            req['symbol'] = symbol
            req['volume'] = volume
            req['price'] = price
            req['hedgeflag'] = '1'
            req['ordertype'] = '1'
            req['exchange'] = exchange
            req['investor'] = investor
            vtOrderID = ctaEngine.sendOrder(req)
            return vtOrderID
        else:
            return None

            # ----------------------------------------------------------------------

    def cancelOrder(self, vtOrderID):
        """撤单"""
        return ctaEngine.cancelOrder(vtOrderID)

    # ----------------------------------------------------------------------

    # ---------------------------------------------------------------------
    def loadDay(self, years, symbol='', exchange='', func=None):
        """载入日K线"""
        symbol = self.vtSymbol if symbol == '' else symbol
        exchange = self.exchange if exchange == '' else exchange
        bars = ctaEngine.getKLineData(symbol, exchange, datetime.datetime.now().strftime('%Y%m%d'), 0, years)
        func = self.onBar if func is None else func
        try:
            for d in bars:
                bar = VtBarData()
                bar.__dict__ = d
                func(bar)
        except:
            self.output(u'历史数据获取失败，使用实盘数据初始化')

    # ---------------------------------------------------------------------

    def loadBar(self, days, symbol='', exchange='', func=None):
        """载入1分钟K线，不大于30天"""
        if days > 30:
            self.output('最多预加载30天的历史1分钟K线数据，请修改参数')
            return

        symbol = self.vtSymbol if symbol == '' else symbol
        exchange = self.exchange if exchange == '' else exchange
        func = self.onBar if func is None else func

        # 将天数切割为3天以内的单元
        divisor, remainder = int(days / 3), days % 3
        days_list = [3] * divisor
        if remainder != 0:
            days_list.append(remainder)

        # 分批次把历史数据取到本地，然后统一load
        bars_list = []
        start_date = datetime.datetime.now().strftime('%Y%m%d')
        while len(days_list) > 0:
            _days = days_list.pop()
            bars = ctaEngine.getKLineData(symbol, exchange, start_date, _days, 0)
            bars_list.append(bars)
            start_date = (datetime.datetime.strptime(bars[0].get('date'), '%Y%m%d') - datetime.timedelta(
                days=1)).strftime('%Y%m%d')
        bars_list.reverse()

        # 处理数据
        for _bars in bars_list:
            try:
                for _bar in _bars:
                    bar = VtBarData()
                    bar.__dict__ = _bar
                    func(bar)
            except Exception:
                self.output('历史数据获取失败，使用实盘数据初始化')

    # ---------------------------------------------------------------------
    def loadTick(self, days):
        """载入Tick"""
        return []

    # ----------------------------------------------------------------------
    def getGui(self):
        """创建界面"""
        if self.__class__.qtsp is not None:
            self.__class__.qtsp.signal.emit(self)

    # ----------------------------------------------------------------------
    def closeGui(self):
        """关闭界面"""
        if self.__class__.qtsp is not None:
            self.__class__.qtsp.signalc.emit(self)

    # ----------------------------------------------------------------------
    def get_investor_account(self, investor):
        """获取资金"""
        account_info = VtAccountData()
        account_raw = ctaEngine.getInvestorAccount(str(investor))
        if account_raw:
            account_info.datetime = datetime.datetime.now()
            account_info.accountID = account_raw.get('InvestorID')
            account_info.vtAccountID = account_raw.get('InvestorID')
            account_info.preBalance = round(account_raw.get('PreBalance'), 2)
            account_info.balance = round(account_raw.get('Balance'), 2)
            account_info.available = round(account_raw.get('Available'), 2)
            account_info.commission = account_raw.get('Fee')
            account_info.margin = account_raw.get('Margin')
            account_info.closeProfit = account_raw.get('CloseProfit')
            account_info.positionProfit = account_raw.get('PositionProfit')
        return account_info

    def get_investor_cost(self, symbol, investor=''):
        investor = self.get_investor() if investor == '' else investor
        cost_infos = list()
        position_raw_infos = ctaEngine.getInvestorPosition(str(investor))
        if position_raw_infos:
            for position_raw_info in position_raw_infos:
                if position_raw_info.get('InstrumentID') == symbol:
                    cost_info = dict()
                    cost_info['symbol'] = symbol
                    cost_info['direction'] = 'LONG' if position_raw_info.get('Direction') == '多' else 'SHORT'
                    cost_info['open_avg_price'] = round(position_raw_info.get('OpenAvgPrice'), 2)
                    cost_info['position_avg_price'] = round(position_raw_info.get('PositionAvgPrice'), 2)
                    cost_info['position_cost'] = round(position_raw_info.get('PositionCost'), 2)
                    cost_infos.append(cost_info)
        return cost_infos

    def get_contract(self, exchange, symbol):
        """获取合约信息"""
        contract_info = VtContractData()
        contract_raw = ctaEngine.getInstrument(exchange, symbol)
        if contract_raw:
            contract_info.vtSymbol = contract_raw.get('Instrument')
            contract_info.symbol = contract_raw.get('Instrument')
            contract_info.exchange = contract_raw.get('Exchange')
            contract_info.name = contract_raw.get('InstrumentName')
            contract_info.productClass = product_cls.get(contract_raw.get('ProductClass'))
            contract_info.size = contract_raw.get('VolumeMultiple')
            contract_info.priceTick = contract_raw.get('PriceTick')
            # 期权相关
            contract_info.strikePrice = contract_raw.get('StrikePrice')
            contract_info.underlyingSymbol = contract_raw.get('UnderlyingInstrID')
            contract_info.optionType = contract_raw.get(contract_raw.get('OptionsType'))
            contract_info.expricedate = contract_raw.get('ExpireDate')
            # SSE的涨跌停
            if contract_info.exchange == 'SSE':
                contract_info.lowerLimit = round(contract_raw.get('LowerLimitPrice'), 2)
                contract_info.upperLimit = round(contract_raw.get('UpperLimitPrice'), 2)
        return contract_info

    def get_InstListByExchAndProduct(self, exchange, product):
        """某个交易所下某个品种的期货合约和期权合约的合约代码"""
        contract_future = list()
        contract_option = list()
        contract_raw = ctaEngine.getInstListByExchAndProduct(str(exchange), str(product))
        # 获取某个交易所下某个品种的期货合约和期权合约的合约信息
        for contract in contract_raw:
            if contract['StrikePrice'] == 0.0 and contract['UnderlyingInstrID'] == str(product):
                contract_future.append(contract['Instrument'])
            elif contract['StrikePrice'] != 0.0:
                contract_option.append(contract['Instrument'])
            else:
                pass
        return contract_future, contract_option

    def get_investor(self, index=1):
        """获取第一个投资者账号"""
        investors_raw = ctaEngine.getInvestorList()
        investors = [investor.get('InvestorID') for investor in investors_raw]
        try:
            return investors[index - 1]
        except IndexError:
            self.output('您设置的投资者账号索引有误，最大值为{0}，您设置的为{1}，请检查确认！'.format(len(investors), index))

    def load_file(self):
        file_location = os.path.join(os.path.abspath(__file__).rsplit('\\', 1)[0], 'files')
        csv_files = os.listdir(file_location)
        result = []
        for csv_file in csv_files:
            with open(os.path.join(file_location, csv_file), 'r') as f:
                rows = csv.DictReader(f)
                result.extend([row for row in rows])
        return result

    # ----------------------------------------------------------------------
    def regTimer(self, tid, mSecs):
        """开启定时器"""
        return ctaEngine.regTimer(self.sid, tid, mSecs)

    def removeTimer(self, tid):
        """关闭定时器"""
        return ctaEngine.removeTimer(self.sid, tid)

    # ----------------------------------------------------------------------
    def getInvestorPosition(self, investorID):
        """获取持仓"""
        return ctaEngine.getInvestorPosition(str(investorID))

    # ----------------------------------------------------------------------
    def output(self, content):
        """输出信息"""
        ctaEngine.writeLog(str(content))

    # ----------------------------------------------------------------------
    def writeCtaLog(self, content):
        """记录CTA日志"""
        content = self.name + ' : ' + str(content)
        ctaEngine.writeLog(content)

    # ----------------------------------------------------------------------
    def putEvent(self):
        """发出策略状态变化事件"""
        setting = OrderedDict()
        setting['sid'] = self.sid
        for key in reversed(self.varList):
            if key in self.varMap:
                setting[self.varMap[key]] = str(getattr(self, key))
        ctaEngine.updateState(setting)


########################################################################
class BarManager(object):
    """
    K线合成器，支持：
    1. 基于Tick合成1分钟K线
    2. 基于1分钟K线合成X分钟K线（X可以是2、3、5、10、15、30、60）
    """

    # ----------------------------------------------------------------------
    def __init__(self, onBar, xmin=0, onXminBar=None):
        """Constructor"""
        self.bar = None  # 1分钟K线对象
        self.onBar = onBar  # 1分钟K线回调函数

        self.xminBar = None  # X分钟K线对象
        self.xmin = xmin  # X的值
        self.onXminBar = onXminBar  # X分钟K线的回调函数

        self.lastTick = None  # 上一TICK缓存对象

    # ----------------------------------------------------------------------
    def updateTick(self, tick):
        """根据TICK更新"""
        newMinute = False  # 默认不是新的一分钟

        # 判断类型
        if type(tick.datetime) is str and tick.datetime != "error":
            tick.datetime = datetime.datetime.strptime(tick.datetime, "%Y-%m-%d %H:%M:%S")
        if self.bar and hasattr(self.bar, "datetime") and (type(self.bar) is str):
            self.bar.datetime = datetime.datetime.strptime(self.bar.datetime, "%Y-%m-%d %H:%M:%S")

        if not self.bar:  # 尚未创建对象
            self.bar = VtBarData()
            newMinute = True
        elif self.bar.datetime.minute != tick.datetime.minute:  # 新的一分钟
            # 生成上一分钟K线的时间戳
            self.bar.datetime = tick.datetime
            self.bar.datetime = self.bar.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
            self.bar.date = self.bar.datetime.strftime('%Y%m%d')
            self.bar.time = self.bar.datetime.strftime('%H:%M:%S.%f')

            # 推送已经结束的上一分钟K线
            self.onBar(self.bar)

            # 创建新的K线对象
            self.bar = VtBarData()
            newMinute = True

        # 初始化新一分钟的K线数据
        if newMinute:
            self.bar.vtSymbol = tick.vtSymbol
            self.bar.symbol = tick.symbol
            self.bar.exchange = tick.exchange

            self.bar.open = tick.lastPrice
            self.bar.high = tick.lastPrice
            self.bar.low = tick.lastPrice
        # 累加更新老一分钟的K线数据
        else:
            self.bar.high = max(self.bar.high, tick.lastPrice)
            self.bar.low = min(self.bar.low, tick.lastPrice)

        # 通用更新部分
        self.bar.close = tick.lastPrice
        self.bar.datetime = tick.datetime
        self.bar.openInterest = tick.openInterest

        if self.lastTick:
            self.bar.volume += (tick.volume - self.lastTick.volume)  # 当前K线内的成交量

        # 缓存Tick
        self.lastTick = tick

    # ----------------------------------------------------------------------
    def updateBar(self, bar):
        """1分钟K线更新"""
        # 尚未创建对象
        if not self.xminBar:
            self.xminBar = VtBarData()

            self.xminBar.vtSymbol = bar.vtSymbol
            self.xminBar.symbol = bar.symbol
            self.xminBar.exchange = bar.exchange

            self.xminBar.open = bar.open
            self.xminBar.high = bar.high
            self.xminBar.low = bar.low

            # 累加老K线
        else:
            self.xminBar.high = max(self.xminBar.high, bar.high)
            self.xminBar.low = min(self.xminBar.low, bar.low)

        # 通用部分
        self.xminBar.close = bar.close
        self.xminBar.datetime = bar.datetime
        self.xminBar.openInterest = bar.openInterest
        self.xminBar.volume += int(bar.volume)

        # X分钟已经走完
        if str(self.xmin).isdigit():
            # X分钟已经走完
            minutes = 60 * bar.datetime.hour + bar.datetime.minute
            if not minutes % self.xmin:  # 可以用X整除
                # 生成上一X分钟K线的时间戳
                self.xminBar.datetime = bar.datetime
                self.xminBar.datetime = self.xminBar.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
                self.xminBar.date = self.xminBar.datetime.strftime('%Y%m%d')
                self.xminBar.time = self.xminBar.datetime.strftime('%H:%M:%S.%f')

                # 推送
                self.onXminBar(self.xminBar)

                # 清空老K线缓存对象
                self.xminBar = None
        else:
            if not self.barDate == bar.datetime.date():  # 可以用X整除
                # 生成上一X分钟K线的时间戳
                self.xminBar.datetime = bar.datetime
                self.xminBar.datetime = self.xminBar.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
                self.xminBar.date = self.xminBar.datetime.strftime('%Y%m%d')
                self.xminBar.time = self.xminBar.datetime.strftime('%H:%M:%S.%f')

                # 推送
                self.onXminBar(self.xminBar)

                # 清空老K线缓存对象
                self.xminBar = None

        self.barDate = bar.datetime.date()


########################################################################
class ArrayManager(object):
    """
    K线序列管理工具，负责：
    1. K线时间序列的维护
    2. 常用技术指标的计算
    """

    # ----------------------------------------------------------------------
    def __init__(self, size=100, maxsize=None, bars=None):
        """Constructor"""

        # 一次性载入
        if bars is not None:
            self.size = size
            self.maxsize = size if maxsize is None else maxsize
            # return self.loadBars(bars)

        # 实盘分次载入
        self.count = 0  # 缓存计数
        self.size = size  # 缓存大小
        self.inited = False  # True if count>=size

        self.maxsize = size if maxsize is None else maxsize

        self.openArray = np.zeros(self.maxsize)  # OHLC
        self.highArray = np.zeros(self.maxsize)
        self.lowArray = np.zeros(self.maxsize)
        self.closeArray = np.zeros(self.maxsize)
        self.volumeArray = np.zeros(self.maxsize)

    # ----------------------------------------------------------------------
    def updateBar(self, bar):
        """更新K线"""
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True
        self.openArray[0:self.maxsize - 1] = self.openArray[1:self.maxsize]
        self.highArray[0:self.maxsize - 1] = self.highArray[1:self.maxsize]
        self.lowArray[0:self.maxsize - 1] = self.lowArray[1:self.maxsize]
        self.closeArray[0:self.maxsize - 1] = self.closeArray[1:self.maxsize]
        self.volumeArray[0:self.maxsize - 1] = self.volumeArray[1:self.maxsize]

        self.openArray[-1] = bar.open
        self.highArray[-1] = bar.high
        self.lowArray[-1] = bar.low
        self.closeArray[-1] = bar.close
        self.volumeArray[-1] = bar.volume
        return self.inited

    # ----------------------------------------------------------------------
    @property
    def open(self):
        """获取开盘价序列"""
        return self.openArray[-self.size:]

    # ----------------------------------------------------------------------
    @property
    def high(self):
        """获取最高价序列"""
        return self.highArray[-self.size:]

    # ----------------------------------------------------------------------
    @property
    def low(self):
        """获取最低价序列"""
        return self.lowArray[-self.size:]

    # ----------------------------------------------------------------------
    @property
    def close(self):
        """获取收盘价序列"""
        return self.closeArray[-self.size:]

    # ----------------------------------------------------------------------
    @property
    def volume(self):
        """获取成交量序列"""
        return self.volumeArray[-self.size:]

    # ----------------------------------------------------------------------
    # ：技术指标
    def sma(self, n, array=False):
        """简单均线"""
        result = talib.SMA(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def std(self, n, array=False):
        """标准差"""
        result = talib.STDDEV(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def cci(self, n, array=False):
        """CCI指标"""
        result = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def kd(self, nf=9, ns=3, array=False):
        """KD指标"""
        slowk, slowd = talib.STOCH(self.high, self.low, self.close,
                                   fastk_period=nf,
                                   slowk_period=ns,
                                   slowk_matype=0,
                                   slowd_period=ns,
                                   slowd_matype=0)
        if array:
            return slowk, slowd
        return slowk[-1], slowd[-1]

    # ----------------------------------------------------------------------
    def hhv(self, n, array=False):
        """移动最高"""
        result = talib.MAX(self.high, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def llv(self, n, array=False):
        """移动最低"""
        result = talib.MIN(self.low, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def kdj(self, n, s, f, array=False):
        """KDJ指标"""
        c = self.close
        hhv = self.hhv(n, True)
        llv = self.llv(n, True)
        shl = talib.SUM(hhv - llv, s)
        scl = talib.SUM(c - llv, s)
        k = 100 * scl / shl
        d = talib.SMA(k, f)
        j = 3 * k - 2 * d
        if array:
            return k, d, j
        return k[-1], d[-1], j[-1]

    # ----------------------------------------------------------------------
    def macdext(self, fastPeriod, slowPeriod, signalPeriod, array=False):
        """MACD指标"""
        macd, signal, hist = talib.MACDEXT(self.close, fastPeriod, 1,
                                           slowPeriod, 1, signalPeriod, 1)
        if array:
            return macd, signal, hist * 2
        return macd[-1], signal[-1], hist[-1] * 2

    # ----------------------------------------------------------------------
    def atr(self, n, array=False):
        """ATR指标"""
        result = talib.ATR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def rsi(self, n, array=False):
        """RSI指标"""
        result = talib.RSI(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def macd(self, fastPeriod, slowPeriod, signalPeriod, array=False):
        """MACD指标"""
        macd, signal, hist = talib.MACD(self.close, fastPeriod,
                                        slowPeriod, signalPeriod)
        if array:
            return macd, signal, hist
        return macd[-1], signal[-1], hist[-1]

    # ----------------------------------------------------------------------
    def adx(self, n, array=False):
        """ADX指标"""
        result = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def boll(self, n, dev, array=False):
        """布林通道"""
        mid = self.sma(n, array)
        std = self.std(n, array)
        up = mid + std * dev
        down = mid - std * dev
        return up, down

        # ----------------------------------------------------------------------

    def keltner(self, n, dev, array=False):
        """肯特纳通道"""
        mid = self.sma(n, array)
        atr = self.atr(n, array)
        up = mid + atr * dev
        down = mid - atr * dev
        return up, down

    # ----------------------------------------------------------------------
    def donchian(self, n, array=False):
        """唐奇安通道"""
        up = talib.MAX(self.high, n)
        down = talib.MIN(self.low, n)
        if array:
            return up, down
        return up[-1], down[-1]

    def kama(self, n, array=False):
        """考夫曼的自适应移动平均线"""
        result = talib.KAMA(self.close, n)
        if array:
            return result
        return result[-1]

    def aroon(self, n, array=False):
        """阿隆指标"""
        aroondown, aroonup = talib.stream_AROON(self.high, self.low, n)
        if array:
            return aroondown, aroonup
        return aroondown[-1], aroonup[-1]

    def bop(self, array=False):
        """均势指标"""
        result = talib.BOP(self.open, self.high, self.low, self.close)
        if array:
            return result
        return result[-1]

    def cci(self, n, array=False):
        """顺势指标"""
        result = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]

    def cmo(self, n, array=False):
        """钱德动量摆动指标"""
        result = talib.CMO(self.close, n)
        if array:
            return result
        return result[-1]

    def willr(self, n, array=False):
        """威廉指标"""
        result = talib.WILLR(self.high, self.low, self.close, n)
        if array:
            return -result
        return -result[-1]

    # 威廉指标TALIB计算和其他方向相关，因此再这里加负号

    def ht_dcperiod(self, array=False):
        """希尔伯特变换-主导周期"""
        result = talib.HT_DCPERIOD(self.close)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    # ：统计学指标
    def beta(self, n, array=False):
        """β系数"""
        result = talib.BETA(self.high, self.low, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def correl(self, n, array=False):
        """皮尔逊相关系数"""
        result = talib.CORREL(self.high, self.low, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def linear(self, n, array=False):
        """线性回归"""
        result = talib.LINEARREG(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def linear_inter(self, n, array=False):
        """线性回归截距指标"""
        result = talib.LINEARREG_INTERCEPT(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def linear_slope(self, n, array=False):
        """线性回归斜率指标"""
        result = talib.LINEARREG_SLOPE(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def tsf(self, n, array=False):
        """时间序列预测"""
        result = talib.TSF(self.close, n)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    def var(self, n, array=False):
        """VAR-总体方差和numpy库var计算结果一致"""
        result = talib.VAR(self.close, n, nbdev=1)
        if array:
            return result
        return result[-1]

    # ----------------------------------------------------------------------
    # ：K线形态识别
    """TALIB中形态识别函数要求传入的参数为numpy.array数组，输出的也是numpy.array数组，
    且里面每个数值范围为【-100,100】，如果数值是0，那就是无模式；根据不同的函数，100，和-100含义不同，
    例如CDLHAMMER，锤头，如果值是100，就是识别了改图型，如果是-100，就是反的图形"""

    def two_crows(self):
        """两只乌鸦"""
        result = talib.CDL2CROWS(self.open, self.high, self.low, self.close)
        return result[-1]

    # ----------------------------------------------------------------------
    def three_black_crows(self):
        """三只乌鸦"""
        result = talib.CDL3BLACKCROWS(self.open, self.high, self.low, self.close)
        return result[-1]

    # ----------------------------------------------------------------------
    def three_stars(self):
        """南方三星"""
        result = talib.CDL3STARSINSOUTH(self.open, self.high, self.low, self.close)
        return result[-1]

    # ----------------------------------------------------------------------
    def hammer(self):
        """锤头"""
        result = talib.CDLHAMMER(self.open, self.high, self.low, self.close)
        return result[-1]

    # ----------------------------------------------------------------------
    def inverted_hammer(self):
        """倒锤头"""
        result = talib.CDLINVERTEDHAMMER(self.open, self.high, self.low, self.close)
        return result[-1]

    # ----------------------------------------------------------------------
    def evening_star(self):
        """幕星"""
        result = talib.CDLEVENINGSTAR(self.open, self.high, self.low, self.close)
        return result[-1]
    ## 更多关于K线形态识别请参考talib库：https://ta-lib.org/


# ----------------------------------------------------------------------
"""期权模块"""


class Option(object):
    author = 'ljt;qq:2032320858'
    """场内欧式期权定价模型包括BS模型，三叉树模型，隐含波动率计算提供二叉树，牛顿迭代，单纯形算法，非线程方差全局求跟四种方式
    。美式期权定价模型：BAW，二叉树，三叉树，最小二乘法;"""

    def __init__(self, cp, s0, k, t, r, sigma, marketp, dv=0):
        self.cp = "Call" if cp in ["c", "C", "Call"] else "Put"
        self.cp_sign = 1.0 if self.cp == 'Call' else -1.0
        self.s0 = s0 * 1.0
        # 标的价格
        self.k = k * 1.0
        # 执行价格
        self.t = t * 1.0
        # 年化剩余到期天数
        self.sigma = sigma * 1.0
        self.r = r * 1.0
        # 无风险利率
        self.dv = dv * 1.0
        # 股息率
        self.marketp = marketp * 1.0
        self.M = ''
        # baw模型中间公式
        self.N = ''
        # baw模型中间公式
        self.K_t = ''
        # baw模型中间公式
        self.q_1 = ''
        self.q_2 = ''
        self.star = ''
        self.A1 = ''
        self.A2 = ''

    # ----------------------------------------------------------------------
    # BS 模型定价相关

    def d_1(self):
        d_1 = (np.log(self.s0 / self.k) + (
                self.r - self.dv + .5 * self.sigma ** 2) * self.t) / self.sigma / np.sqrt(self.t)
        return d_1

    def d_2(self):
        d_2 = self.d_1() - self.sigma * np.sqrt(self.t)
        return d_2

    def d_1_1(self):
        d_1_1 = (1 / np.sqrt(2 * np.pi)) * np.exp((-self.d_1() ** 2) / 2)
        return d_1_1

    def d_2_1(self):
        d_2_1 = (1 / np.sqrt(2 * np.pi)) * np.exp((-self.d_2() ** 2) / 2)
        return d_2_1

    def BS_price(self):
        valueprice = self.cp_sign * self.s0 * np.exp(-self.dv * self.t) * sps.norm.cdf(self.cp_sign * self.d_1()) \
                     - self.cp_sign * self.k * np.exp(-self.r * self.t) * sps.norm.cdf(self.cp_sign * self.d_2())
        return valueprice

    def BS_Delta(self):
        minuend = 0 if self.cp_sign == 1.0 else 1
        delta = (sps.norm.cdf(self.d_1()) - minuend) * np.exp(-self.dv * self.t)
        return delta

    def BS_Gamma(self):
        Gamma = np.exp(-self.dv * self.t) * self.d_1_1() / (self.s0 * self.sigma * np.sqrt(self.t))
        return Gamma

    def BS_Vega(self):
        Vega = self.s0 * np.sqrt(self.t) * np.exp(-self.dv * self.t) * self.d_1_1()
        return Vega

    def BS_Theta(self):
        """折合为每天的时间损耗率"""
        year_theta = (
            (-self.s0 * np.exp(-self.dv * self.t) * self.d_1_1() * self.sigma) /
            (2 * np.sqrt(self.t)) -
            self.cp_sign * self.r * sps.norm.cdf(self.cp_sign * self.d_2()) *
            self.k * np.exp(-self.r * self.t) +
            self.cp_sign * self.dv * self.s0 *
            sps.norm.cdf(self.cp_sign * self.d_1()) * np.exp(-self.dv * self.t)
        )
        day_theta = year_theta / 365
        return day_theta

    def BS_Rho(self):
        Rho = self.cp_sign * self.k * self.t * np.exp(-self.r * self.t) * sps.norm.cdf(self.cp_sign * self.d_2())
        return Rho

    def BS_RhoQ(self):
        RhoQ = self.cp_sign * self.s0 * self.t * np.exp(-self.dv * self.t) * sps.norm.cdf(self.cp_sign * self.d_1())
        return RhoQ

    def BS_Vanna(self):
        Vanna = -np.exp(-self.dv * self.t) * self.d_1_1() * self.d_2() / self.sigma
        return Vanna

    def BS_IV(self):
        """二分法计算隐含波动率"""
        top = 2  # 波动率上限
        floor = 0.01  # 波动率下限
        count = 0  # 计数器
        min_precision = 0.00001  # 精度

        if self.cp_sign == 1.0:
            if self.s0 * np.exp(-self.dv * self.t) - self.k * np.exp(-self.r * self.t) >= self.marketp:
                sigma = 0.8
                return sigma
        elif self.cp_sign == -1.0:
            if self.k * np.exp(-self.r * self.t) - self.s0 * np.exp(-self.dv * self.t) >= self.marketp:
                sigma = 0.8
                return sigma

        o_top = Option(self.cp, self.s0, self.k, self.t, self.r, top, self.marketp, self.dv)
        o_floor = Option(self.cp, self.s0, self.k, self.t, self.r, floor, self.marketp, self.dv)
        
        while (abs(o_floor.BS_price() - self.marketp) >= min_precision) and \
                (abs(o_top.BS_price() - self.marketp) >= min_precision):
            sigma = (floor + top) / 2
            o_mid = Option(self.cp, self.s0, self.k, self.t, self.r, sigma, self.marketp, self.dv)
            if abs(o_mid.BS_price() - self.marketp) <= min_precision:
                top = floor = sigma
                return sigma
            elif (o_floor.BS_price() - self.marketp) * (o_mid.BS_price() - self.marketp) < 0:
                top = sigma
            else:
                floor = sigma
            count += 1
            if count > 200:
                sigma = 0
                return sigma

    def BS_IV_newton(self):
        """牛顿迭代法计算隐含波动率"""
        max_count = 200
        min_precision = 0.01
        sigma = 0.5
        if self.cp_sign == 1.0:
            if self.s0 * np.exp(-self.dv * self.t) - self.k * np.exp(-self.r * self.t) >= self.marketp:
                sigma = 0.8
                return sigma
            else:
                pass
        elif self.cp_sign == -1.0:
            if self.k * np.exp(-self.r * self.t) - self.s0 * np.exp(-self.dv * self.t) >= self.marketp:
                sigma = 0.8
                return sigma
            else:
                pass
        for i in range(0, max_count):
            o_mid = Option(self.cp, self.s0, self.k, self.t, self.r, sigma, self.marketp, self.dv)
            price = o_mid.BS_price()
            vega = o_mid.BS_Vega()
            diff = self.marketp - price
            if abs(diff) < min_precision:
                return sigma
            sigma = sigma + diff / vega
        return sigma

    def BS_IV_func(self, sigma):
        d_1 = (np.log(self.s0 / self.k) + (
                self.r - self.dv + .5 * sigma ** 2) * self.t) / sigma / np.sqrt(self.t)
        d_2 = d_1 - sigma * np.sqrt(self.t)
        vpirec = self.cp_sign * self.s0 * np.exp(-self.dv * self.t) * sps.norm.cdf(self.cp_sign * d_1) \
                 - self.cp_sign * self.k * np.exp(-self.r * self.t) * sps.norm.cdf(self.cp_sign * d_2)
        return abs(self.marketp - vpirec)

    def BS_IV_optimize(self):
        """单纯形算法计算隐含波动率"""
        try:
            IV = opt.minimize(self.BS_IV_func, self.sigma, method='nelder-mead')
            return IV.x[0]
        except:
            ctaEngine.writeLog(str('超出边界'))

    def BS_IV_root(self):
        """通过非线性方程求根来计算隐含波动率"""
        try:
            IV = opt.root(self.BS_IV_func, self.sigma)
            return IV.x[0]
        except:
            ctaEngine.writeLog(str('超出边界'))

    # ----------------------------------------------------------------------
    # 二叉树模型定价相关
    def CRR_m(self):
        """无息标的的二叉树美式期权定价模型"""
        N = 5000
        # 二叉树步数
        dt = self.t / N
        # 时间拆分
        u = np.exp(self.sigma * np.sqrt(dt))
        d = 1.0 / u
        a = np.exp(self.r * dt)
        p = (a - d) / (u - d)
        q = 1.0 - p
        value = np.zeros(N + 1)
        s_t = np.array([(self.s0 * u ** j * d ** (N - j)) for j in range(N + 1)])
        if self.cp_sign == 1.0:
            value = np.maximum(s_t - self.k, 0)
        else:
            value = np.maximum(self.k - s_t, 0)
        for _ in range(N - 1, -1, -1):
            value[:-1] = np.exp(-self.r * dt) * (p * value[1:] + q * value[:-1])
            s_t = s_t * u
            if self.cp_sign == 1.0:
                value = np.maximum(value, s_t - self.k)
            else:
                value = np.maximum(value, self.k - s_t)
        return value

    def CRR_m_price(self):
        """定价价格"""
        return self.CRR_m()[0]

    def CRR_m_Delta(self):
        """delta"""
        delta = (self.CRR_m()[2] - self.CRR_m()[1]) / (self.s0 * (np.exp(self.sigma * np.sqrt(self.t / 5000)) - 1 /
                                                                  (np.exp(self.sigma * np.sqrt(self.t / 5000)))))
        return delta

    def CRR_m_Gamma(self):
        """gamma"""
        change = abs(
            (self.CRR_m()[5] - self.CRR_m()[4]) / (self.s0 * (np.exp(self.sigma * np.sqrt(self.t / 5000))) ** 2 -
                                                   self.s0)) - abs(
            (self.CRR_m()[4] - self.CRR_m()[3]) / (self.s0 - self.s0 * (1 /
                                                                        np.exp(
                                                                            self.sigma * np.sqrt(self.t / 5000))) ** 2))
        h = 0.5 * self.s0 * ((np.exp(self.sigma * np.sqrt(self.t / 5000))) ** 2 - (1 /
                                                                                   np.exp(self.sigma * np.sqrt(
                                                                                       self.t / 5000))) ** 2)
        gamma = change / h
        return gamma

    def CRR_m_Vega(self):
        """vega"""
        f = self.CRR_m_price()
        self.sigma = self.sigma + 0.01
        f_change = self.CRR_m_price()
        vega = (f_change - f) * 100
        self.sigma = self.sigma - 0.01
        return vega

    def CRR_m_Theta(self):
        """theta"""
        # theta = (self.CRR_m()[4] - self.CRR_m()[0]) / 2 * (self.t / 5000)
        # return theta
        f = self.CRR_m_price()
        self.t = self.t - 1 / 365
        f_change = self.CRR_m_price()
        theta = (f_change - f)
        self.t = self.t + 1 / 365
        return theta

    def CRR_m_Rho(self):
        """rho"""
        f = self.CRR_m_price()
        self.r = self.r + 0.01
        f_change = self.CRR_m_price()
        rho = (f_change - f) * 100
        self.r = self.r - 0.01
        return rho

    # ----------------------------------------------------------------------
    # 最小二乘法定价相关

    def Lsm(self):
        """蒙特卡洛最小二乘估计美式期权定价模型"""
        N = 1000
        path = 1000
        # 模拟路径个数
        dt = self.t / (N - 1)
        # 时间划分
        df = np.exp(self.r * dt)
        x0 = np.zeros((path, 1))
        increments = sps.norm.rvs(loc=(self.r - self.sigma ** 2 / 2) * dt, scale=np.sqrt(dt) * self.sigma,
                                  size=(path, N - 1))
        x = np.concatenate((x0, increments), axis=1).cumsum(1)
        s = self.s0 * np.exp(x)
        if self.cp_sign == 1:
            hv = np.maximum(s - self.k, 0)
        else:
            hv = np.maximum(self.k - s, 0)
        v = np.zeros_like(hv)
        v[:, -1] = hv[:, -1]
        for i in range(N - 2, 0, -1):
            path_in = hv[:, i] > 0
            ev = np.polyfit(s[path_in, i], v[path_in, i + 1] * df, 2)
            c = np.polyval(ev, s[path_in, i])
            exercise = np.zeros(len(path_in), dtype=bool)
            exercise[path_in] = hv[path_in, i] > c
            v[exercise, i] = hv[exercise, i]
            v[exercise, i + 1:] = 0
            path_out = (hv[:, i] == 0)
            v[path_out, i] = v[path_out, i + 1] * df
        v0 = np.mean(v[:, 1]) / df
        return v0

    # ----------------------------------------------------------------------
    # Baw期权定价模型相关

    def Baw_func(self, s0):
        """定价模型方程"""
        self.M = 2 * self.r / self.sigma ** 2
        # baw模型中间公式
        self.N = 2 * (self.r - self.dv) / self.sigma ** 2
        # baw模型中间公式
        self.K_t = 1 - np.exp(-self.r * self.t)
        # baw模型中间公式
        self.q_1 = 0.5 * (-self.N + 1 - np.sqrt((self.N - 1) ** 2 + 4 * self.M / self.K_t))
        self.q_2 = 0.5 * (-self.N + 1 + np.sqrt((self.N - 1) ** 2 + 4 * self.M / self.K_t))
        if self.cp_sign == 1:
            value_1 = self.BS_price()
            value_2 = np.exp((self.dv - self.r) * self.t)
            value_3 = (1 - value_2 * sps.norm.cdf(self.d_1_sx(s0))) * s0 / self.q_2
            return (value_1 + value_3 - s0 + self.k) ** 2
        else:
            value_1 = self.BS_price()
            value_2 = np.exp((self.dv - self.r) * self.t)
            value_3 = (1 - value_2 * sps.norm.cdf(-self.d_1_sx(s0))) * s0 / self.q_1
            return (value_1 - value_3 + s0 - self.k) ** 2

    def d_1_sx(self, s0):
        d_1_sx = (np.log(s0 / self.k) + (
                self.r - self.dv + .5 * self.sigma ** 2) * self.t) / self.sigma / np.sqrt(self.t)
        return d_1_sx

    def Baw_simulate(self):
        """定价模型方程求解"""
        data = opt.fmin(self.Baw_func, self.s0)
        self.star = data[0]
        return

    def A(self):
        if self.cp_sign == 1:
            self.A1 = 0
            self.A2 = 1 - np.exp((- self.r + self.dv) * self.t) * sps.norm.cdf(self.d_1_sx(s0=self.star))
            self.A2 = self.A2 * (self.d_1_sx(s0=self.star) / self.q_2)
            return
        else:
            self.A1 = 1 - np.exp((- self.r + self.dv) * self.t) * sps.norm.cdf(-self.d_1_sx(s0=self.star))
            self.A1 = -self.A1 * (self.d_1_sx(s0=self.star) / self.q_1)
            self.A2 = 0
            return

    def Baw_price(self):
        """Baw美式期权定价模型"""
        self.Baw_simulate()
        self.A()
        if self.cp_sign == 1:
            if self.s0 >= self.star:
                Baw_price = self.s0 - self.k
                return Baw_price
            else:
                Baw_price = self.BS_price() + self.A2 * (self.s0 / self.star) ** self.q_2
                return Baw_price
        else:
            if self.s0 <= self.star:
                Baw_price = self.k - self.s0
                return Baw_price
            else:
                Baw_price = self.BS_price() + self.A1 * (self.s0 / self.star) ** self.q_1
                return Baw_price

    def Baw_Delta(self):
        """Baw美式期权定价模型Delta"""
        self.Baw_simulate()
        self.A()
        if self.cp_sign == 1:
            delta = self.BS_Delta() + (self.A2 * self.q_2) / self.s0 * (self.s0 / self.star) / self.q_2
            return delta
        else:
            delta = self.BS_Delta() + (self.A1 * self.q_1) / self.s0 * (self.s0 / self.star) / self.q_1
            return delta

    def Baw_Gamma(self):
        """Baw美式期权定价模型Gamma"""
        self.Baw_simulate()
        self.A()
        if self.cp_sign == 1:
            gamma = self.BS_Gamma() + (self.A2 * self.q_2 * (self.q_2 - 1)) / self.s0 ** 2 * (
                        self.s0 / self.star) / self.q_2
            return gamma
        else:
            gamma = self.BS_Gamma() + (self.A1 * self.q_1 * (self.q_1 - 1)) / self.s0 ** 2 * (
                        self.s0 / self.star) / self.q_1
            return gamma

    def Baw_Vega(self):
        """Baw美式期权定价模型Vega"""
        f = self.Baw_price()
        self.sigma = self.sigma + 0.01
        f_change = self.Baw_price()
        vega = (f_change - f) * 100
        self.sigma = self.sigma - 0.01
        return vega

    def Baw_Theta(self):
        """Baw美式期权定价模型theta,日度"""
        f = self.Baw_price()
        self.t = self.t - 1.0 / 365
        f_change = self.Baw_price()
        theta = (f_change - f) 
        self.t = self.t + 1.0 / 365
        return theta

    def Baw_Rho(self):
        """Baw美式期权定价模型Rho"""
        f = self.Baw_price()
        self.r = self.r + 0.01
        f_change = self.Baw_price()
        rho = (f_change - f) * 100
        self.r = self.r - 0.01
        return rho

    def Baw_IV(self):
        """二分法计算Baw美式期权隐含波动率"""
        top = 2  # 波动率上限
        floor = 0.01  # 波动率下限
        count = 0  # 计数器
        min_precision = 0.00001  # 精度
        if self.cp_sign == 1.0:
            if self.s0 * np.exp(-self.dv * self.t) - self.k * np.exp(-self.r * self.t) >= self.marketp:
                sigma = 0.8
                return sigma
            else:
                pass
        elif self.cp_sign == -1.0:
            if self.k * np.exp(-self.r * self.t) - self.s0 * np.exp(-self.dv * self.t) >= self.marketp:
                sigma = 0.8
                return sigma
            else:
                pass
        o_top = Option(self.cp, self.s0, self.k, self.t, self.r, top, self.marketp, self.dv)
        o_floor = Option(self.cp, self.s0, self.k, self.t, self.r, floor, self.marketp, self.dv)
        while abs(top - floor) > min_precision or (abs(o_floor.Baw_price() - self.marketp) >= min_precision
                                                   and min_precision <= abs(o_top.Baw_price() - self.marketp)
                                                   >= min_precision):
            sigma = (floor + top) / 2
            o_mid = Option(self.cp, self.s0, self.k, self.t, self.r, sigma, self.marketp, self.dv)
            if abs(o_mid.Baw_price() - self.marketp) <= min_precision:
                return sigma
                break
            elif (o_floor.Baw_price() - self.marketp) * (o_mid.Baw_price() - self.marketp) < 0:
                top = sigma
            else:
                floor = sigma
            count += 1
            if count > 200:
                sigma = 0
                return sigma
                break

    # ----------------------------------------------------------------------
    # 美式三叉树定价相关

    def Back_tree_m(self):
        """美式三叉树定价模型"""
        N = 3500
        # 步长个人经验暂定3500，太长会影响计算性能，太短精度不够
        dt = self.t / N
        dx = self.sigma * np.sqrt(3 * dt)
        niu = self.r - self.dv - 0.5 * self.sigma ** 2
        pu = 0.5 * dt * ((self.sigma / dx) ** 2 + niu / dx)
        pm = 1 - dt * (self.sigma / dx) ** 2 - self.r * dt
        pd = 0.5 * dt * ((self.sigma / dx) ** 2 - niu / dx)
        set_array = self.s0 * np.exp(dx * np.linspace(-N, N, 2 * N + 1))
        strike_array = self.k * np.ones(len(set_array))
        if self.cp_sign == 1:
            value = np.maximum(set_array - strike_array, 0)
        else:
            value = np.maximum(strike_array - set_array, 0)
        for i in range(1, N + 1):
            length = len(value)
            option_value = np.zeros(length)

            option_value[i:length - i] = pu * value[i + 1:length - i + 1] + pm * value[i:length - i] \
                                         + pd * value[i - 1:length - i - 1]
            if self.cp_sign == 1.0:
                option_value = np.maximum(option_value, set_array - strike_array)
            else:
                option_value = np.maximum(option_value, strike_array - set_array)
            value = option_value
        return value[N]

    # ----------------------------------------------------------------------
    # 欧式三叉树定价相关
    def Back_tree(self):
        """标准欧式三叉树定价模型"""
        N = 3500
        # 步长个人经验暂定3500，太长会影响计算性能，太短精度不够
        dt = self.t / N
        dx = self.sigma * np.sqrt(3 * dt)
        niu = self.r - self.dv - 0.5 * self.sigma ** 2
        pu = 0.5 * dt * ((self.sigma / dx) ** 2 + niu / dx)
        pm = 1 - dt * (self.sigma / dx) ** 2 - self.r * dt
        pd = 0.5 * dt * ((self.sigma / dx) ** 2 - niu / dx)
        set_array = self.s0 * np.exp(dx * np.linspace(-N, N, 2 * N + 1))
        strike_array = self.k * np.ones(len(set_array))
        if self.cp_sign == 1:
            value = np.maximum(set_array - strike_array, 0)
        else:
            value = np.maximum(strike_array - set_array, 0)
        for i in range(1, N + 1):
            length = len(value)
            option_value = np.zeros(length)

            option_value[i:length - i] = pu * value[i + 1:length - i + 1] + pm * value[i:length - i] \
                                         + pd * value[i - 1:length - i - 1]
            value = option_value
        return value[N]


# ----------------------------------------------------------------------

class Montecarlo:
    """ 蒙特卡洛模拟一揽子欧式期权定价，可用于场外欧式期权定价 """

    def __init__(self, cp, N_samples, D_stock, t, s0, r, sigma_vector, correl_matrix, M_vector, k):
        self.cp = 'Call' if (cp == 'C' or cp == 'c') else 'Put'
        self.cp_sign = 1.0 if self.cp == 'Call' else -1.0
        self.N_samples = N_samples
        # 样本容量
        self.D_stock = D_stock
        # 标的个数
        self.t = t
        # 年化剩余到期日期
        self.s0 = s0
        # 标的初始价格向量
        self.r = r
        # 无风险利率向量
        self.sigma_vector = sigma_vector
        # 波动率向量
        self.correl_matrix = correl_matrix
        # 多维联合正态分布的相关系数矩阵
        self.M_vector = M_vector
        # 权重因子向量
        self.k = k
        # 执行价

    def Analog(self):
        # 蒙特卡洛采样N次
        s0 = np.array(self.s0).reshape((self.D_stock, 1))
        chol = slin.cholesky(self.correl_matrix, lower=True)
        # Cholesky 分解
        s_mat = np.empty((self.D_stock, 1))
        for i in range(self.N_samples):
            u = np.random.uniform(size=self.D_stock)
            z = np.array(sps.norm.ppf(u)).reshape((self.D_stock, 1))
            ratio = np.exp(
                np.array((self.r - 0.5 * np.square(self.sigma_vector)) * self.t).reshape((self.D_stock, 1)) + (
                        self.t ** 0.5) * np.dot(self.sigma_vector * chol, z))
            s_k = s0 * ratio
            s_mat = np.hstack((s_mat, s_k))
        s_mat = s_mat[:, 1:self.N_samples + 1]
        s_price = np.dot(np.array(self.M_vector), s_mat)
        # 一揽子标的的价格
        if self.cp_sign == 1.0:
            call = s_price - self.k
            for index in range(len(s_price)):
                if call[index] < 0:
                    call[index] = 0
            result = np.exp(-self.r[0] * self.t) * np.mean(call)
            return result
        else:
            put = self.k - s_price
            for index in range(len(s_price)):
                if put[index] < 0:
                    put[index] = 0
            result = np.exp(-self.r[0] * self.t) * np.mean(put)
            return result

    """ 调用方法参数示例：
        cp='c' 
        D_stock=5 标的个数
        sigma_vector=[0.3]*D_stock  波动率向量，每个标的的波动率
        T=1  年化剩余到期天数
        S0=[20]*D_stock  每个标的价格
        r=[0.03]*D_stock  无风险利率向量
        MV=[0.25,0.25,0.25,0.25]  每个标的的权重因子向量
        K=30  执行价
        cor = 0.5  
        CorMat_1 = np.array([[1, cor, cor, cor,cor],
                             [0, 1, cor, cor,cor],
                             [0, 0, 1, cor,cor],
                             [0, 0, 0, 1,cor],
                             [0, 0, 0, 0,1]])
        CorMat_1 += CorMat_1.T - np.diag(CorMat_1.diagonal()) 多维联合正态分布的相关系数矩阵
        N = 10000  样本容量 """
