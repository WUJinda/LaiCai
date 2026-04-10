# encoding: UTF-8

'''
本文件包含了CTA引擎中策略开发用模板(目前支持双合约)
last update: 2023年10月13日 11:45:56
'''
import copy
import datetime
import gc
import json
import os
import sys
import time
from collections import OrderedDict, defaultdict
from functools import reduce
from threading import Thread, Timer
from traceback import format_exc
from typing import Any, Dict, List, Literal, Union

import numpy as np
import pandas as pd
import qdarkstyle
import talib
from PyQt5 import QtCore
from PyQt5.QtGui import QCloseEvent, QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget

import ctaEngine  # type: ignore
import utils
from ctaBase import *
from models import Position
from uiKLine import KLineWidget
from vtConstant import *
from vtObject import (AccountData, ContractData, ContractStatusData, KLineData,
                      OrderData, TickData, TradeData, option_type, product_cls)


class StatusCode(object):
    """与无限易客户端交互状态码"""
    stop = 20001


class CtaTemplate(object):
    """策略模板"""
    t: Thread = None
    qtsp: 'QtGuiSupport' = None

    name: str = ""  # 策略实例名称

    def __init__(self, ctaEngine=None, setting={}):
        self.base_param_list = [
            'name',
            'className',
            'vtSymbol',
            'exchange',
            'investor'
        ]

        self.base_var_list = [
            'inited',
            'trading',
            'pos'                                                                                                                                                                                                                                                                                                                                                                                                         
        ]

        self.paramMap: Dict[str, str] = {}
        self.varMap: Dict[str, str] = {}

        self.limit_time = 2

        # 无限易客户端需要
        self.sid = 0  # 策略ID
        self.vtSymbol = ''  # 合约
        self.exchange = ''  # 交易的合约vt系统代码
        self.investor = ''
        self.volume = 0

        # 策略的基本变量，由引擎管理
        self.inited = False  # 是否进行了初始化
        self.trading = False  # 是否启动交易，由引擎管理

        self.bar = None  # K线对象

        self.orderID = None  # 上一笔订单
        self.tradeDate = None  # 当前交易日

        # 仓位信息
        self.pos: Dict[str, int] = {}  # 总投机方向
        self.tpos0L: Dict[str, int] = {}  # 今持多仓
        self.tpos0S: Dict[str, int] = {}  # 今持空仓
        self.ypos0L: Dict[str, int] = {}  # 昨持多仓
        self.ypos0S: Dict[str, int] = {}  # 昨持空仓

        # 定义尾盘，判断是否要进行交易
        self.endOfDay = False
        self.buySig = False
        self.shortSig = False
        self.coverSig = False
        self.sellSig = False

        # 默认交易价格
        self.longPrice = 0.0  # 多头开仓价
        self.shortPrice = 0.0  # 空头开仓价

        self.symbolList = []  # 所有需要订阅的合约
        self.exchangeList = []  # 所有需要订阅合约的交易所
        self.symExMap = {}

        self.widget: KLWidget = None
        self.paramLoaded = False

        self.on_tick_data = TickData()

    @property
    def paramList(self) -> List[str]:
        """参数列表"""
        return self.base_param_list + list(self.paramMap.keys())
    
    @property
    def varList(self) -> List[str]:
        """状态列表"""
        return self.base_var_list + list(self.varMap.keys())

    @property
    def className(self) -> str:
        """策略类的名称"""
        return self.__class__.__name__

    @property
    def json_file(self) -> str:
        """参数保存文件"""
        json_path = os.path.join(os.path.dirname(__file__), 'json')
        return os.path.join(json_path, f"{self.name}.json")

    def onUpdate(self, setting: dict) -> None:
        """将保存的 json 文件配置设置为对应的类属性"""
        for key, value in setting.items():
            if key in self.paramList and key != "className":
                setattr(self, key, value)

        # 所有需要订阅的合约
        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')
        self.symExMap = dict(zip(self.symbolList, self.exchangeList))

        # 初始化仓位信息
        self.pos = {}  # 总投机方向
        self.tpos0L = {}  # 今持多仓
        self.tpos0S = {}  # 今持空仓
        self.ypos0L = {}  # 昨持多仓
        self.ypos0S = {}  # 昨持空仓
        for symbol in self.symbolList:
            if not symbol: continue
            self.pos[symbol] = 0
            self.ypos0L[symbol] = 0
            self.tpos0L[symbol] = 0
            self.ypos0S[symbol] = 0
            self.tpos0S[symbol] = 0

    @classmethod
    def setQtSp(cls):
        """启动 QT 界面"""
        if cls.t is None:
            cls.t = Thread(target=cls.StartGui)
            cls.t.setDaemon(True)
            cls.t.start()


    def subSymbol(self):
        """订阅合约"""
        for symbol, exchange in zip(self.symbolList, self.exchangeList):
            ctaEngine.subMarketData({
                'sid': self,
                'InstrumentID': str(symbol),
                'ExchangeID': str(exchange)
            })


    def unSubSymbol(self):
        """取消订阅合约"""
        for symbol, exchange in zip(self.symbolList, self.exchangeList):
            ctaEngine.unsubMarketData({
                'sid': self,
                'InstrumentID': str(symbol),
                'ExchangeID': str(exchange)
            })


    def setParam(self, setting: dict):
        """刷新参数, 修改界面参数时调用"""
        params = {"sid": self.sid}
        map_keys = list(self.paramMap.keys())
        map_values = list(self.paramMap.values())

        for key, value in setting.items():
            #: 更新类属性, 并把更新后的数据回传给无限易
            params[key.encode('gbk')] = setting[key]
            class_attr_name = map_keys[map_values.index(key)]
            if class_attr_name != 'vtSymbol' and utils.isdigit(value):
                #: 证券代码是纯数字, 不能转成整型
                value = eval(value)
            setattr(self, class_attr_name, value)

        # 初始化仓位信息
        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')

        self.pos: Dict[str, int] = {}
        self.tpos0L: Dict[str, int] = {}
        self.tpos0S: Dict[str, int] = {}
        self.ypos0L: Dict[str, int] = {}
        self.ypos0S: Dict[str, int] = {}

        for symbol in self.symbolList:
            if not symbol: continue
            self.pos[symbol] = 0
            self.ypos0L[symbol] = 0
            self.tpos0L[symbol] = 0
            self.ypos0S[symbol] = 0
            self.tpos0S[symbol] = 0

        ctaEngine.updateParam(params)
        self.putEvent()

    def getParam(self):
        """获取参数"""
        setting = OrderedDict()
        for key in self.paramList:
            if key in self.paramMap:
                setting[self.paramMap[key]] = str(getattr(self, key))
        return setting

    def getParamOrgin(self):
        """获取参数,onStop时调用"""
        setting = {}
        for key in self.paramList:
            setting[key] = getattr(self, key)
        return setting

    def onInit(self) -> None:
        """初始化策略"""
        if (
            self.paramLoaded is False
            and os.path.exists(self.json_file)
            and os.path.getsize(self.json_file)
        ):
            with open(self.json_file, "r") as f:
                setting: dict = json.load(f)
                self.onUpdate(setting)
                f.close()

            self.output("使用保存数据初始化")
            self.paramLoaded = True

        self.inited = True
        self.putEvent()
        self.output("策略初始化完毕")

    def onStart(self) -> None:
        """启动策略"""
        self.trading = True

        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')
        self.symExMap = dict(zip(self.symbolList, self.exchangeList))

        self.subSymbol()
        self.output('策略启动')
        self.manage_position()
        self.putEvent()
        if self.widget:
            self.widget.load_data_signal.emit()

    def onStop(self) -> None:
        """停止策略"""
        self.trading = False

        self.unSubSymbol()
        self.output("策略停止")

        with open(self.json_file, "w") as f:
            setting = self.getParamOrgin()
            json.dump(setting, f)
            f.close()

        self.output("保存策略参数")

        self.closeGui()
        self.putEvent()

    def onTick(self, tick: TickData) -> None:
        """收到行情 tick 推送"""
        self.on_tick_data.update(tick)
        # 判断交易日更新
        if self.tradeDate is None or self.tradeDate != tick.date:
            self.tradeDate = tick.date
            for symbol in self.symbolList:
                self.set_default_position(symbol)
                self.ypos0L[symbol] += self.tpos0L[symbol]
                self.tpos0L[symbol] = 0
                self.ypos0S[symbol] += self.tpos0S[symbol]
                self.tpos0S[symbol] = 0
    
    def onContractStatus(self, contractStatus: ContractStatusData) -> None:
        """合约状态变化"""
        return

    def onOrderCancel(self, order: OrderData) -> None:
        """收到委托撤单推送"""
        self.orderID = None

    def onOrderTrade(self, order: OrderData) -> None:
        """收到委托成交推送"""
        self.orderID = None

    def onOrder(self, order: OrderData, log: bool = False) -> None:
        """收到委托变化推送，发单成功也算委托变化"""
        if not order:
            return
        # 对于无需做细粒度委托控制的策略，可以忽略 onOrder
        offset = order.offset
        status = order.status
        if status == '已撤销':
            self.onOrderCancel(order)
        elif status == '全部成交' or status == '部成部撤':
            self.onOrderTrade(order)
        if log:
            self.output(' '.join([offset, status]))


    def onErr(self, error: dict) -> None:
        """收到错误推送"""
        self.trading = False

        def limit_contorl():
            self.trading = True
            self.output("错单流控已关闭")

        if error['errCode'] == '0004':
            self.output(f"错单流控开启，{self.limit_time} 秒后关闭，错单原因：{error['errMsg']}")
            Timer(self.limit_time, limit_contorl).start()
        else:
            self.output(error)


    def onTimer(self, tid: int) -> None:
        """收到定时推送"""
        pass


    def onTrade(self, trade: TradeData, log: bool = False) -> None:
        """成交推送"""
        if not trade:
            return

        volume = trade.volume
        symbol = trade.vtSymbol
        offset = trade.offset
        is_shfe_or_ine = trade.exchange in ["SHFE", "INE"]

        self.set_default_position(symbol)

        if trade.direction == "多":
            self.pos[symbol] += volume
            if offset == '开仓':
                self.tpos0L[symbol] += volume
            elif is_shfe_or_ine:
                (self.tpos0S if offset == "平今" else self.ypos0S)[symbol] -= volume
            elif offset in ["平今", "平仓", "平昨"]:
                self.tpos0S[symbol] -= volume
                if self.tpos0S[symbol] < 0:
                    self.ypos0S[symbol] += self.tpos0S[symbol]
                    self.tpos0S[symbol] = 0
        elif trade.direction == "空":
            self.pos[symbol] -= volume
            if offset == '开仓':
                self.tpos0S[symbol] += volume
            elif is_shfe_or_ine:
                (self.tpos0L if offset == "平今" else self.ypos0L)[symbol] -= volume
            elif offset in ["平今", "平仓", "平昨"]:
                self.tpos0L[symbol] -= volume
                if self.tpos0L[symbol] < 0:
                    self.ypos0L[symbol] += self.tpos0L[symbol]
                    self.tpos0L[symbol] = 0
        if log:
            self.output(f"onTrade: {trade.tradeTime} 合约:{symbol}|{trade.direction}{offset}成交:{trade.price}|手数:{volume}")
        gc.collect()


    def getCtaIndicator(self, bar: KLineData) -> None:
        pass

    def getCtaSignal(self, bar: KLineData) -> None:
        pass

    def onBar(self, bar: KLineData) -> None:
        """收到 Bar 推送"""
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
        self.execSignal(1)

        # 发出状态更新事件
        self.putEvent()

    def onXminBar(self, bar: KLineData) -> None:
        """收到 x 分钟 Bar 推送"""
        return

    def execSignal(self, volume: int) -> None:
        """简易交易信号执行"""
        return

    def sync_position(self) -> None:
        """同步持仓"""
        self.position = {}

        for investor in ctaEngine.getInvestorList():
            investor_id: str = investor["InvestorID"]
            investor_position: List[dict] = ctaEngine.getInvestorPosition(investor_id)

            group_position = {}

            for _position in investor_position:
                (
                    group_position
                    .setdefault(_position['InstrumentID'], {})
                    .setdefault(_position["HedgeFlag"], [])
                    .append(_position)
                )

            for instrument in group_position:
                for hedge_flag in group_position[instrument]:
                    position = Position(group_position[instrument][hedge_flag])

                    (
                        self.position
                        .setdefault(investor_id, {})
                        .setdefault(instrument, {})
                        .setdefault(hedge_flag, position)
                    )

    def get_position(
        self,
        instrument: str,
        hedgeflag: Literal["1", "2", "3", "4", "5"] = "1",
        investor: str = None
    ) -> Position:
        """
        获取持仓
        
        Args:
            instrument: 合约代码\n
            hedgeflag: 投机套保标志\n
                1 投机（默认）, 2 套利, 3 套保, 4 做市商, 5 备兑
            investor: 资金帐号
        """
        self.sync_position()

        if not investor:
            investor = self.get_investor()

        return self.position.get(investor, {}).get(instrument, {}).get(hedgeflag, Position())

    def manage_position(self, index: int=1) -> None:
        """处理账户（默认第一个）的持仓情况"""
        pos_list = self.getInvestorPosition(self.get_investor(index))
        for symbol in self.symbolList:
            self.pos[symbol] = 0
        for pos in pos_list:
            if pos['InstrumentID'] in self.symbolList:
                if pos['Direction'] == '多':
                    self.pos[pos['InstrumentID']] += pos['Position']
                    # 昨持多仓
                    self.ypos0L[pos['InstrumentID']] = pos['YdPositionClose']
                    # 今持多仓
                    self.tpos0L[pos['InstrumentID']] = pos['Position'] - pos['YdPositionClose']
                elif pos['Direction'] == '空':
                    self.pos[pos['InstrumentID']] -= pos['Position']
                    # 昨持空仓
                    self.ypos0S[pos['InstrumentID']] = pos['YdPositionClose']
                    # 今持空仓
                    self.tpos0S[pos['InstrumentID']] = pos['Position'] - pos['YdPositionClose']

    def set_default_position(self, symbol: str):
        """持仓字典中不存在该合约则需要设置一个默认值, 防止触发 KeyError"""
        self.pos.setdefault(symbol, 0)
        self.ypos0L.setdefault(symbol, 0)
        self.tpos0L.setdefault(symbol, 0)
        self.ypos0S.setdefault(symbol, 0)
        self.tpos0S.setdefault(symbol, 0)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def sell_y(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖平昨"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_SELL, price, volume, symbol, exchange, investor, memo=memo)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def sell_t(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖平今"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor, memo=memo)

    def buy(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_BUY, price, volume, symbol, exchange, investor, memo=memo)

    def short(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_SHORT, price, volume, symbol, exchange, investor, memo=memo)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def cover_y(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买平昨"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_COVER, price, volume, symbol, exchange, investor, memo=memo)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def cover_t(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买平今"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrder(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor, memo=memo)

    def buy_fok(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrderFOK(CTAORDER_BUY, price, volume, symbol, exchange, investor, memo=memo)

    def short_fok(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrderFOK(CTAORDER_SHORT, price, volume, symbol, exchange, investor, memo=memo)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def sell_fok(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖平"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        if (tpos0L := self.tpos0L.get(symbol)) >= volume:
            return self.sendOrderFOK(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor, memo=memo)
        elif (ypos0L := self.ypos0L.get(symbol)) >= volume:
            return self.sendOrderFOK(CTAORDER_SELL, price, volume, symbol, exchange, investor, memo=memo)
        self.output(f'NO ORDER WARN(sell_fok): 今持多仓:{tpos0L}, 昨持多仓:{ypos0L}, 报单数:{volume}')

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def cover_fok(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买平"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        if (tpos0S := self.tpos0S.get(symbol)) >= volume:
            return self.sendOrderFOK(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor, memo=memo)
        elif (ypos0S := self.ypos0S.get(symbol)) >= volume:
            return self.sendOrderFOK(CTAORDER_COVER, price, volume, symbol, exchange, investor, memo=memo)
        self.output(f'NO ORDER WARN(cover_fok): 今持空仓:{tpos0S}, 昨持空仓:{ypos0S}, 报单数:{volume}')

    def buy_fak(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrderFAK(CTAORDER_BUY, price, volume, symbol, exchange, investor, memo=memo)

    def short_fak(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖开"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        return self.sendOrderFAK(CTAORDER_SHORT, price, volume, symbol, exchange, investor, memo=memo)

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def sell_fak(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """卖平"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        if (tpos0L := self.tpos0L.get(symbol)) >= volume:
            return self.sendOrderFAK(CTAORDER_SELL_TODAY, price, volume, symbol, exchange, investor, memo=memo)
        elif (ypos0L := self.ypos0L.get(symbol)) >= volume:
            return self.sendOrderFAK(CTAORDER_SELL, price, volume, symbol, exchange, investor, memo=memo)
        self.output(f'NO ORDER WARN(sell_fak): 今持多仓:{tpos0L}, 昨持多仓:{ypos0L}, 报单数:{volume}')

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def cover_fak(self, price, volume, symbol='', exchange='', memo=None, investor=''):
        """买平"""
        symbol = symbol or self.symbolList[0]
        exchange = exchange or self.symExMap.get(symbol, '')
        if (tpos0S := self.tpos0S.get(symbol)) >= volume:
            return self.sendOrderFAK(CTAORDER_COVER_TODAY, price, volume, symbol, exchange, investor, memo=memo)
        elif (ypos0S := self.ypos0S.get(symbol)) >= volume:
            return self.sendOrderFAK(CTAORDER_COVER, price, volume, symbol, exchange, investor, memo=memo)
        self.output(f'NO ORDER WARN(cover_fok): 今持空仓:{tpos0S}, 昨持空仓:{ypos0S}, 报单数:{volume}')

    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def cover(self, *args, **kwargs): ...
    @utils.deprecated("auto_close_position", ctaEngine.writeLog)
    def sell(self, *args, **kwargs): ...

    def auto_close_position(
        self,
        price: Union[float, int],
        volume: int,
        symbol: str,
        exchange: str,
        order_direction: Literal["buy", "sell"],
        investor: str = "",
        memo: str = None,
        shfe_close_first: bool = False,
        hedgeflag: str = "1",
        order_type: str = "0"
    ) -> Union[int, None]:
        """
        自动平仓，默认平今优先

        Args:
            order_direction: 买卖方向: buy 买入平仓, sell 卖出平仓
            shfe_close_first: 上期平仓优先
            hedgeflag: 投机套保方向: 1 投机, 2 套利, 3 套保, 4 做市商, 5 备兑
            order_type: 交易指令: 0 GFD, 1 FAK, 2 FOK
        """

        def _send_order(_order_direction: str, _volume: int) -> Union[int, None]:
            return self._make_order_req(
                order_type=order_type,
                order_direction=_order_direction,
                price=price,
                volume=_volume,
                symbol=symbol,
                exchange=exchange,
                investor=investor,
                hedgeflag=hedgeflag,
                memo=memo
            )

        if order_direction == "buy":
            order_direction_text = "买平"
            direction = "short"
        elif order_direction == "sell":
            order_direction_text = "卖平"
            direction = "long"
        else:
            self.output("[自动平仓] 买卖方向错误")
            return

        position = self.get_position(
            instrument=symbol,
            hedgeflag=hedgeflag,
            investor=investor
        ).get_single_position(direction)

        position_t: int = position.td_close_available
        position_y: int = position.yd_close_available

        _order_flag = False

        if exchange in ["SHFE", "INE"]:
            def _shfe_send_order(_position: int, _order_direction: str) -> Union[None, int]:
                nonlocal volume
                _volume = _position if volume >= _position else volume
                volume -= _volume

                if (order_id := _send_order(_order_direction, _volume)) is not None:
                    self.output(f"[自动平仓] {_order_direction} {_volume} 手, order_id {order_id}")

                if volume == 0:
                    #: 仓全部平完
                    return order_id

            if shfe_close_first and position_y > 0:
                #: 上期所或能源中心优先平昨
                if (order_id := _shfe_send_order(position_y, order_direction_text)) or volume == 0:
                    return order_id
                position_y = 0
                _order_flag = True

            if position_t > 0:
                #: 上期所或能源中心平今
                if (order_id := _shfe_send_order(position_t, f"{order_direction_text}今")) or volume == 0:
                    return order_id
                position_t = 0
                _order_flag = True

        close_available = position_t + position_y

        if close_available == 0:
            if _order_flag is False and self.trading:
                self.output("[自动平仓] 可平仓量为 0")
            return

        if close_available < volume:
            if self.trading:
                self.output("[自动平仓] 可平仓量小于报单数，将使用可平仓量报单")
            volume = close_available

        return _send_order(order_direction_text, volume)

    def _make_order_req(
        self,
        order_type: str,
        order_direction: str,
        **kwargs
    ) -> Union[int, None]:
        """发送委托请求, 请勿直接使用本方法
        Args:
            order_type: 0 GFD, 1 FAK, 2 FOK
            order_direction: 交易方向类型, 常量
            kwargs: 下单参数
                market: 0 非市价单, 1 市价单
        Returns:
            int 类型的 order id
        """
        if not self.trading:
            return

        req = {
            'sid': self.sid,
            'ordertype': order_type,
            'hedgeflag': '1',
        }

        req.update(kwargs)
        req['memo'] = memo.encode('gbk') if (memo := str(req['memo'])) else ''

        if order_direction in [CTAORDER_BUY, CTAORDER_COVER, CTAORDER_COVER_TODAY]:
            req['direction'] = '0'
        elif order_direction in [CTAORDER_SHORT, CTAORDER_SELL, CTAORDER_SELL_TODAY]:
            req['direction'] = '1'

        if order_direction in [CTAORDER_BUY, CTAORDER_SHORT]:
            req['offset'] = '0'
        elif order_direction in [CTAORDER_SELL, CTAORDER_COVER]:
            req['offset'] = '1'
        elif order_direction in [CTAORDER_SELL_TODAY, CTAORDER_COVER_TODAY]:
            req['offset'] = '3'

        return ctaEngine.sendOrder(req)

    def sendOrder(self, orderType, price, volume, symbol, exchange, investor='', memo=None) -> Union[int, None]:
        """发送 GFD 指令委托"""
        return self._make_order_req(
            order_type='0',
            order_direction=orderType,
            symbol=symbol,
            volume=volume,
            price=price,
            exchange=exchange,
            investor=investor,
            memo=memo
        )

    def sendOrderFAK(self, orderType, price, volume, symbol, exchange, investor='', memo=None) -> Union[int, None]:
        """发送 FAK 指令委托"""
        return self._make_order_req(
            order_type='1',
            order_direction=orderType,
            symbol=symbol,
            volume=volume,
            price=price,
            exchange=exchange,
            investor=investor,
            memo=memo
        )

    def sendOrderFOK(self, orderType, price, volume, symbol, exchange, investor='', memo=None) -> Union[int, None]:
        """发送 FOK 指令委托"""
        return self._make_order_req(
            order_type='2',
            order_direction=orderType,
            symbol=symbol,
            volume=volume,
            price=price,
            exchange=exchange,
            investor=investor,
            memo=memo
        )

    def sendOrderMarketFAK(self, orderType, volume, symbol, exchange, investor='', memo=None) -> Union[int, None]:
        """发送市价 FAK 指令委托: 支持中金所, 郑商所, 大商所, 上证, 深证"""
        return self._make_order_req(
            order_type='1',
            order_direction=orderType,
            market=1,
            symbol=symbol,
            volume=volume,
            price=0,
            exchange=exchange,
            investor=investor,
            memo=memo
        )


    def cancelOrder(self, vtOrderID):
        """撤单"""
        return ctaEngine.cancelOrder(vtOrderID)

    def loadDay(self, years, symbol='', exchange='', func=None):
        """载入日K线"""
        symbol = self.vtSymbol if symbol == '' else symbol
        exchange = self.exchange if exchange == '' else exchange
        bars = ctaEngine.getKLineData(symbol, exchange, datetime.datetime.now().strftime('%Y%m%d'), 0, years)
        func = self.onBar if func is None else func
        try:
            for d in bars:
                bar = KLineData()
                bar.__dict__.update(d)
                bar.datetime = datetime.datetime.strptime(d["date"], "%Y%m%d")
                func(bar)
        except:
            self.output('历史数据获取失败，使用实盘数据初始化')

    @staticmethod
    def deleteDuplicate(lst: list) -> list:
        """对列表里的字典去重"""
        func = lambda x, y: x if y in x else x + [y]
        lst = reduce(func, [[], ] + lst)
        return lst

    def loadBar(self, days: int, symbol=None, exchange=None, func=None, qt_gui=False) -> None:
        """载入1分钟K线，不大于30天"""
        if qt_gui:
            for _ in range(5):
                #: 如果没有 K 线 UI 没加载全, 会导致线图为空
                if not self.qtsp:
                    self.output("QT 为空")
                    time.sleep(0.5)

        if days > 30:
            self.output('最多预加载30天的历史1分钟K线数据，请修改参数')
            return

        symbol = symbol or self.vtSymbol
        exchange = exchange or self.exchange
        func = func or self.onBar

        if not all([symbol, exchange]):
            raise TypeError("错误：交易所或合约为空！")

        # 将天数切割为3天以内的单元
        time_gap = 3
        divisor = int(days / time_gap)
        days_list = [time_gap] * divisor
        if (remainder:=days % time_gap) != 0:
            days_list.insert(0, remainder)

        # 分批次把历史数据取到本地，然后统一load
        bars_list = []
        now_time = datetime.datetime.now()
        start_date = now_time.strftime('%Y%m%d')
        start_time = now_time.strftime("%H:%M:%S")
        for _days in days_list:
            bars: list = ctaEngine.getKLineData(symbol, exchange, start_date, _days, 0, start_time, 1)
            if not bars:
                raise ValueError(f"错误：请检查参数是否填写正确：[{exchange} {symbol}]")
            bars.reverse()
            bars_list.extend(bars)
            start_date = bars[-1].get('date')
            start_time = bars[-1].get('time')

        # 处理数据
        try:
            for _bar in self.deleteDuplicate(bars_list[::-1]):
                bar = KLineData()
                bar.__dict__.update(_bar)
                func(bar)
        except Exception as e:
            self.output(format_exc())
            self.output(f'历史数据获取失败，使用实盘数据初始化 {e}')

    def getGui(self):
        """创建界面"""
        for _ in range(10):
            if not self.qtsp:
                time.sleep(0.5)
        if self.qtsp:
            self.qtsp.init_widget_signal.emit(self)

    def closeGui(self):
        """关闭界面"""
        if self.qtsp:
            self.qtsp.hide_signal.emit(self)

    def pause_strategy(self) -> None:
        """暂停策略"""
        ctaEngine.pauseStrategy(self.sid)

    def get_investor_account(self, investor: str) -> AccountData:
        """获取资金"""
        account_info = AccountData()
        account_raw = ctaEngine.getInvestorAccount(str(investor))
        if account_raw:
            account_info.query_time = datetime.datetime.now()
            account_info.investor = account_raw.get('InvestorID')
            account_info.accountID = account_raw.get('AccountID')
            
            account_info.preBalance = round(account_raw.get('PreBalance'), 2)
            account_info.balance = round(account_raw.get('Balance'), 2)

            account_info.pre_available = round(account_raw.get('PreAvailable'), 2)
            account_info.available = round(account_raw.get('Available'), 2)

            account_info.commission = round(account_raw.get('Fee'), 2)

            account_info.frozen_margin = round(account_raw.get('FrozenMargin'), 2)
            account_info.margin = round(account_raw.get('Margin'), 2)
            
            account_info.closeProfit = round(account_raw.get('CloseProfit'), 2)
            account_info.positionProfit = round(account_raw.get('PositionProfit'), 2)
            account_info.dynamic_rights = round(account_raw.get('DynamicRights'), 2)

            account_info.risk = round(account_raw.get('Risk'), 6)
            account_info.deposit = round(account_raw.get('Deposit'), 2)
            account_info.withdraw = round(account_raw.get('Withdraw'), 2)

        return account_info

    def get_investor_cost(self, symbol: str, investor: str=None) -> List[dict]:
        """获取合约持仓成本"""
        investor = investor or self.get_investor()
        cost_infos: List[dict] = []
        position_data: List[dict] = ctaEngine.getInvestorPosition(str(investor))

        for position in position_data:
            if position.get("InstrumentID") == symbol:
                cost_infos.append({
                    "symbol": symbol,
                    "direction": 'LONG' if position.get('Direction') == '多' else 'SHORT',
                    "open_avg_price": round(position.get('OpenAvgPrice'), 2),
                    "position_avg_price": round(position.get('PositionAvgPrice'), 2),
                    "position_cost": round(position.get('PositionCost'), 2),
                })

        return cost_infos

    def get_contract(self, exchange: str, symbol: str) -> ContractData:
        """获取合约信息"""
        contract_info = ContractData()
        contract_raw: dict = ctaEngine.getInstrument(exchange, symbol)

        if instrument := contract_raw.get("Instrument"):
            contract_info.vtSymbol = instrument
            contract_info.symbol = instrument
            contract_info.exchange = contract_raw.get('Exchange')
            contract_info.name = contract_raw.get('InstrumentName')
            contract_info.productClass = product_cls.get(contract_raw.get('ProductClass'))
            contract_info.size = contract_raw.get('VolumeMultiple')
            contract_info.priceTick = contract_raw.get('PriceTick')
            contract_info.min_limit_order_volume = contract_raw.get('MinLimitOrderVolume')
            contract_info.max_limit_order_volume = contract_raw.get('MaxLimitOrderVolume')
            contract_info.expire_date = contract_raw.get('ExpireDate')

            # 期权相关
            contract_info.strikePrice = contract_raw.get('StrikePrice')
            contract_info.underlyingSymbol = contract_raw.get('UnderlyingInstrID')
            contract_info.optionType = option_type.get(contract_raw.get('OptionsType'))

            if contract_info.exchange == 'SSE':
                """SSE的涨跌停"""
                contract_info.lowerLimit = round(contract_raw.get('LowerLimitPrice'), 2)
                contract_info.upperLimit = round(contract_raw.get('UpperLimitPrice'), 2)

        return contract_info

    def get_InstListByExchAndProduct(self, exchange: str, product: str) -> dict:
        """获取某个交易所下某个品种的期货合约和期权合约的合约信息
        product_class 键所代表的含义:
        期货: 1
        期权: 2
        交易所套利: 3
        即期: 4
        期转现: 5
        未知类型: 6
        证券: 7
        股票期权: 8
        金交所现货: 9
        金交所递延: a
        金交所远期: b
        现货期权: h
        外汇: c
        TAS 合约: d
        金属指数: e
        """
        contract_data = {}
        contract_raw = ctaEngine.getInstListByExchAndProduct(str(exchange), str(product))
        for contract in contract_raw:
            contract_data.setdefault(contract['ProductClass'], []).append(contract['Instrument'])
        return contract_data

    def get_investor(self, index: int=1) -> Union[str, None]:
        """获取投资者信息"""
        investors_raw = ctaEngine.getInvestorList()
        investors = [investor.get('InvestorID') for investor in investors_raw]
        try:
            return investors[index - 1]
        except IndexError:
            self.output(f'您设置的投资者账号索引有误，最大值为{len(investors)}，您设置的为{index}，请检查确认！')

    def regTimer(self, tid: int, mSecs: int) -> int:
        """注册定时器
        tid: 定时器 id
        mSecs: 毫秒, 定时器多久运行一次"""
        return ctaEngine.regTimer(self.sid, tid, mSecs)

    def removeTimer(self, tid: int) -> int:
        """移除定时器
        tid: 定时器 id"""
        return ctaEngine.removeTimer(self.sid, tid)

    def getInvestorPosition(self, investorID: str) -> List[dict]:
        """获取持仓"""
        return ctaEngine.getInvestorPosition(str(investorID))

    def output(self, *content: Any) -> None:
        """输出信息到控制台"""
        log_time = datetime.datetime.now().replace(microsecond=0)
        ctaEngine.writeLog(f"[{log_time}] [{self.name}] {' '.join(map(str, content))}")

    def writeCtaLog(self, content: Any) -> None:
        """记录CTA日志"""
        ctaEngine.writeLog(f"{self.name}: {content}")

    def putEvent(self):
        """发出策略状态变化事件"""
        setting = OrderedDict()
        setting['sid'] = self.sid
        for key in reversed(self.varList):
            if key in self.varMap:
                setting[self.varMap[key]] = str(getattr(self, key))
        ctaEngine.updateState(setting)

    @classmethod
    def StartGui(cls):
        # 设置Qt的皮肤
        try:
            app = QApplication([''])
            app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
            basePath = os.path.split(os.path.realpath(__file__))[0]
            cfgfile = QtCore.QFile(os.path.join(basePath, 'css.qss'))
            cfgfile.open(QtCore.QFile.ReadOnly)
            styleSheet = bytes(cfgfile.readAll()).decode('utf-8')
            app.setStyleSheet(styleSheet)
            # 界面设置
            cls.qtsp = QtGuiSupport()
            # 在主线程中启动Qt事件循环
            sys.exit(app.exec_())
        except:
            ctaEngine.writeLog(format_exc())
        cls.t = None


CtaTemplate.setQtSp() #: 启动 QT 界面


class BarManager(object):
    """K 线合成器, 即将弃用, 请使用 MinKLineGenerator"""

    def __init__(self, onBar, xmin=0, onXminBar=None):
        self.bar = None  # 1分钟K线对象
        self.onBar = onBar  # 1分钟K线回调函数

        self.xminBar = None  # X分钟K线对象
        self.xmin = xmin  # X的值
        self.onXminBar = onXminBar  # X分钟K线的回调函数

        self.lastTick = None  # 上一TICK缓存对象
        self.barDate = None # K 线的时间

    def updateTick(self, tick: TickData) -> None:
        """ TICK 更新"""
        newMinute = False  # 默认不是新的一分钟

        # 判断类型
        if type(tick.datetime) is str:
            tick.datetime = datetime.datetime.strptime(tick.datetime, "%Y-%m-%d %H:%M:%S")
        if self.bar and isinstance(getattr(self.bar, "datetime", None), str):
            self.bar.datetime = datetime.datetime.strptime(self.bar.datetime, "%Y-%m-%d %H:%M:%S")

        if not self.bar: # 尚未创建对象
            self.bar = KLineData()
            newMinute = True
        elif self.bar.datetime.minute != tick.datetime.minute: # 新的一分钟
            # 生成上一分钟K线的时间戳
            self.bar.datetime = tick.datetime
            self.bar.datetime = self.bar.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
            self.bar.date = self.bar.datetime.strftime('%Y%m%d')
            self.bar.time = self.bar.datetime.strftime('%H:%M:%S.%f')

            # 推送已经结束的上一分钟K线
            self.onBar(self.bar)

            # 创建新的K线对象
            self.bar = KLineData()
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


    def updateBar(self, bar):
        """1分钟K线更新"""
        # 尚未创建对象
        if not self.xminBar:
            self.xminBar = KLineData()

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



class ArrayManager(object):
    """K 线序列管理工具, 即将弃用, 请使用 MinKLineGenerator"""

    def __init__(self, size=1000, maxsize=None):
        self.count = 0  # 缓存计数
        self.size = size  # 缓存大小
        self.maxsize = maxsize or size
        self.inited = False  # True if count>=size

        self.openArray = np.zeros(self.maxsize)  # OHLC
        self.highArray = np.zeros(self.maxsize)
        self.lowArray = np.zeros(self.maxsize)
        self.closeArray = np.zeros(self.maxsize)
        self.volumeArray = np.zeros(self.maxsize)
        self.datetimeArray = np.zeros(self.maxsize)

    def updateBar(self, bar: KLineData) -> bool:
        """更新K线序列"""
        self.count += 1
        if not self.inited and self.count >= self.size:
            self.inited = True

        self.openArray = np.append(np.delete(self.openArray, 0), bar.open)
        self.highArray = np.append(np.delete(self.highArray, 0), bar.high)
        self.lowArray = np.append(np.delete(self.lowArray, 0), bar.low)
        self.closeArray = np.append(np.delete(self.closeArray, 0), bar.close)
        self.volumeArray = np.append(np.delete(self.volumeArray, 0), bar.volume)
        self.datetimeArray = np.append(np.delete(self.datetimeArray, 0), bar.datetime)

        return self.inited

    @property
    def open(self) -> np.ndarray:
        """获取开盘价序列"""
        return self.openArray[-self.size:]

    @property
    def high(self) -> np.ndarray:
        """获取最高价序列"""
        return self.highArray[-self.size:]

    @property
    def low(self) -> np.ndarray:
        """获取最低价序列"""
        return self.lowArray[-self.size:]

    @property
    def close(self) -> np.ndarray:
        """获取收盘价序列"""
        return self.closeArray[-self.size:]

    @property
    def volume(self) -> np.ndarray:
        """获取成交量序列"""
        return self.volumeArray[-self.size:]

    @property
    def datetime(self) -> np.ndarray:
        """获取时间序列"""
        return self.datetimeArray[-self.size:]


    def sma(self, n, array=False):
        """简单均线"""
        result = talib.SMA(self.close, n)
        if array:
            return result
        return result[-1]

    def ema(self, n, array=False):
        """EXPMA 指标"""
        result = talib.EMA(self.close, n)
        return result if array else result[-1]

    def std(self, n, array=False):
        """标准差"""
        result = talib.STDDEV(self.close, n)
        if array:
            return result
        return result[-1]


    def cci(self, n, array=False):
        """CCI指标"""
        result = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]


    def kd(self, nf=9, ns=3, array=False):
        """KD指标"""
        c = self.close
        hhv = self.hhv(nf, True)
        llv = self.llv(nf, True)
        shl = hhv - llv
        scl = c - llv
        shl = shl[~np.isnan(shl)]
        scl = scl[~np.isnan(scl)]
        rsv = 100 * scl / shl
        k = self.sma1(rsv, ns, 1, 50)
        d = self.sma1(k, ns, 1, 50)
        if array:
            return k, d
        return k[-1], d[-1]


    def hhv(self, n, array=False):
        """移动最高"""
        result = talib.MAX(self.high, n)
        if array:
            return result
        return result[-1]


    def llv(self, n, array=False):
        """移动最低"""
        result = talib.MIN(self.low, n)
        if array:
            return result
        return result[-1]


    def kdj(self, n, s, f, array=False):
        """KDJ指标"""
        c = self.close
        hhv = self.hhv(n, True)
        llv = self.llv(n, True)
        shl = hhv - llv
        scl = c - llv
        shl = shl[~np.isnan(shl)]
        scl = scl[~np.isnan(scl)]
        rsv = 100 * scl / shl
        k = self.sma1(rsv, s, 1, 50)
        d = self.sma1(k, s, 1, 50)
        j = 3 * k - 2 * d
        if array:
            return k, d, j
        return k[-1], d[-1], j[-1]

    def sma1(self, arr: np.ndarray, n: int, m: int, inity: int):
        """移动平均"""
        y = inity
        result = []
        for x in arr:
            if np.isnan(x):
                continue
            y = (m * x + (n - m) * y) / n
            result.append(y)
        return np.array(result)

    def macdext(self, fastPeriod, slowPeriod, signalPeriod, array=False):
        """MACD指标"""
        macd, signal, hist = talib.MACDEXT(self.close, fastPeriod, 1,
                                           slowPeriod, 1, signalPeriod, 1)
        if array:
            return macd, signal, hist * 2
        return macd[-1], signal[-1], hist[-1] * 2


    def atr(self, n, array=False):
        """ATR指标"""
        c = self.close[:-1]
        high = self.high[1:]
        low = self.low[1:]
        hl = high-low
        cl = abs(c - low)
        ch = abs(c - high)
        tr = self.arr_max(hl, cl, ch)
        atr = talib.SMA(tr, n)

        if array:
            return atr, tr
        return atr[-1], tr[-1]

    def xmax(self, arr1: np.ndarray, arr2: np.ndarray) -> np.ndarray:
        """交错最大值"""
        result = list(map(max, zip(arr1[1:], arr2[:-1])))
        return np.array(result)

    def xmin(self, arr1: np.ndarray, arr2: np.ndarray) -> np.ndarray:
        """交错最小值"""
        result = list(map(min, zip(arr1[1:], arr2[:-1])))
        return np.array(result)

    def arr_max(self, *array: np.ndarray) -> np.ndarray:
        """多数组取最值构成新数组"""
        result = list(map(max, zip(*array)))
        return np.array(result)


    def rsi(self, n, array=False):
        """RSI指标"""
        result = talib.RSI(self.close, n)
        if array:
            return result
        return result[-1]


    def macd(self, fastPeriod, slowPeriod, signalPeriod, array=False):
        """MACD指标"""
        macd, signal, hist = talib.MACD(self.close, fastPeriod,
                                        slowPeriod, signalPeriod)
        if array:
            return macd, signal, hist
        return macd[-1], signal[-1], hist[-1]


    def adx(self, n, array=False):
        """ADX指标"""
        result = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]


    def boll(self, n, dev, array=False):
        """布林通道"""
        mid = self.sma(n, array)
        std = self.std(n, array)

        up = mid + std * dev
        down = mid - std * dev

        return up, down


    def keltner(self, n, dev, array=False):
        """肯特纳通道"""
        mid = self.sma(n, array)
        atr = self.atr(n, array)

        up = mid + atr * dev
        down = mid - atr * dev

        return up, down


    def donchian(self, n, array=False):
        """唐奇安通道"""
        up = talib.MAX(self.high, n)
        down = talib.MIN(self.low, n)

        if array:
            return up, down
        return up[-1], down[-1]


class QtGuiSupport(QtCore.QObject):
    """支持 QT 的对象类"""
    init_widget_signal = QtCore.pyqtSignal(object)
    hide_signal = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.widgetDict: Dict[str, QWidget] = {}
        self.init_widget_signal.connect(self.init_strategy_widget)
        self.hide_signal.connect(self.hide_strategy_widget)

    def init_strategy_widget(self, s: CtaTemplate):
        """初始化 widget 或对策略类的 widget 重新赋值"""
        try:
            if s.widgetClass is not None:
                if self.widgetDict.get(s.name) is None:
                    s.widget: QWidget = s.widgetClass(s)
                    self.widgetDict[s.name] = s.widget
                else:
                    s.widget: QWidget = self.widgetDict[s.name]
                    self.widgetDict[s.name].strategy = s

                if uiKLine := getattr(self.widgetDict[s.name], "uiKLine", None):
                    uiKLine.layout_title.setText(s.vtSymbol, bold=True, color="w")
        except:
            ctaEngine.writeLog(format_exc())

    def hide_strategy_widget(self, s: CtaTemplate):
        """隐藏 widget"""
        if s.widgetClass and self.widgetDict.get(s.name):
            self.widgetDict[s.name].hide()


class KLWidget(QWidget):
    """简单交易组件"""
    update_kline_signal = QtCore.pyqtSignal(dict)
    load_data_signal = QtCore.pyqtSignal()
    set_xrange_event_signal = QtCore.pyqtSignal()

    def __init__(self, strategy, parent=None):
        super().__init__(parent)
        self.strategy: CtaTemplate = strategy # 策略实例 CTATemplate
        self.started = True
        self.init_ui()
        self.klines: List[dict] = []
        self.state_data = defaultdict(list)

        self.update_kline_signal.connect(self.update_kline)
        self.load_data_signal.connect(self.load_kline_data)
        self.set_xrange_event_signal.connect(self.uiKLine.set_xrange_event)

        self._first_add = True

    @property
    def main_indicator(self) -> List[str]:
        """主图指标"""
        return self.strategy.mainSigs

    @property
    def sub_indicator(self) -> List[str]:
        """副图指标"""
        return self.strategy.subSigs

    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle(f"策略-{self.strategy.name}")
        self.uiKLine = KLineWidget(self)

        # 整合布局
        vbox = QVBoxLayout()
        vbox.addWidget(self.uiKLine)
        self.setLayout(vbox)
        self.resize(750, 850)

        image_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "image")
        if os.path.exists(image_path):
            for image_file in os.listdir(image_path):
                if image_path.endswith(".ico"):
                    self.setWindowIcon(QIcon(os.path.join(image_path, image_file)))

    @utils.deprecated("recv_kline", ctaEngine.writeLog)
    def addBar(self, data):
        """弃用, 仅做兼容"""
        self.recv_kline(data)

    def recv_kline(self, data: dict) -> None:
        """接受 K 线"""
        if self.strategy.trading:
            self.update_kline_signal.emit(data)
        else:
            if self._first_add:
                self.clear()
            self.klines.append(data["bar"].__dict__)
            for s in (self.main_indicator + self.sub_indicator):
                self.state_data[s].append(data[s])

        self.update_bs_signal(data["sig"])
        self._first_add = False

    def update_kline(self, data: dict):
        """更新 K 线"""
        kline: KLineData = data["bar"]

        if (
            len(self.klines) >= 2
            and (self.klines[-2]["datetime"] < kline.datetime < self.klines[-1]["datetime"])
        ):
            """丢数据"""
            self.klines.insert(-1, kline.__dict__)
            self.uiKLine.insert_kline(kline)

            for indicator_name in self.main_indicator + self.sub_indicator:
                self.state_data[indicator_name].insert(-1, data[indicator_name])

            self.update_indicator_data(new_data=True)

            return

        is_new_kline = self.uiKLine.update_kline(kline)

        if is_new_kline:
            self.klines.append(kline.__dict__)
        else:
            self.klines[-1] = kline.__dict__

        self.update_indicator_data(data, new_data=is_new_kline)

        self.uiKLine.update_candle_signal.emit()

        self.plot_main()
        self.plot_sub()

    def update_bs_signal(self, price: float):
        """设置买卖信号的坐标"""
        if price:
            index = len(self.klines) - 1
            self.uiKLine.buy_sell_signals[index] = price

            if self.strategy.trading:
                self.uiKLine.add_buy_sell_signal.emit(index)

    def load_kline_data(self):
        """载入历史 K 线数据"""
        if self._first_add is False:
            """只有调用了 recv_kline 才需要重新载入数据"""
            pdData = pd.DataFrame(self.klines).set_index("datetime")
            pdData["openInterest"] = pdData["openInterest"].astype(float)
            self.uiKLine.load_data(pdData)
            self.uiKLine.plotMark()
            self.update_indicator_data()
            self.uiKLine.plot_all()
            self.plot_main()
            self.plot_sub()

        self._first_add = True
        self.show()

    def clear(self):
        """清空数据"""
        self.klines.clear()
        self.state_data.clear()
        self.uiKLine.clear_data()
        self.uiKLine.clear_buy_sell_signals()
        self.uiKLine.plot_all()
        self.started = False

    def update_indicator_data(self, data: dict = None, new_data: bool = True):
        """更新指标数组中的数据"""
        if data:
            for s in self.main_indicator + self.sub_indicator:
                if new_data:
                    self.state_data[s].append(data[s])
                else:
                    self.state_data[s][-1] = data[s]

        for s in self.main_indicator:
            if s in self.uiKLine.indicator_data:
                _indicator_data: np.ndarray = (
                    np.array(self.state_data[s])
                    if new_data
                    else np.append(self.uiKLine.indicator_data[s][:-1], data[s])
                )
                self.uiKLine.indicator_data[s] = _indicator_data

        for s in self.sub_indicator:
            self.uiKLine.sub_indicator_data[s] = np.array(self.state_data[s])

    def plot_main(self):
        """输出信号到主图"""
        for indicator_name in self.main_indicator:
            _indicator_data: np.ndarray = np.array(self.state_data[indicator_name])
            if indicator_name in self.uiKLine.indicator_data:
                self.uiKLine.indicator_plot_items[indicator_name].setData(
                    _indicator_data,
                    pen=self.uiKLine.indicator_color_map[indicator_name],
                    name=indicator_name
                )
            else:
                self.uiKLine.showSig({indicator_name: _indicator_data})

    def plot_sub(self):
        """输出信号到副图"""
        for indicator_name in self.sub_indicator:
            self.uiKLine.showSig(
                datas={indicator_name: np.array(self.state_data[indicator_name])},
                main_plot=False
            )

    def closeEvent(self, evt: QCloseEvent) -> None:
        """继承关闭事件"""
        if self.strategy.trading:
            QMessageBox.warning(None, "警告", "策略启动时无法关闭，暂停时会自动关闭！")
        else:
            self.hide()
        evt.ignore()
