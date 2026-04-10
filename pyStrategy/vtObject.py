# encoding: UTF-8
import datetime
import json
import os
import sys
import traceback
from dataclasses import dataclass
from importlib import machinery

qt_origin_path = os.path.join(sys.base_prefix, "Lib", "site-packages", "PyQt5", "Qt", "plugins")
if os.path.exists(qt_origin_path):
    #: 正确设置 QT 路径
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = qt_origin_path


import ctaEngine  # type: ignore

from models import Base, DateTimeType
from vtConstant import *

product_cls = {
    '1': '期货',
    '2': '期权',
    '3': '组合',
    '4': '即期',
    '5': '期转现',
    '6': '未知类型',
    '7': '证券',
    '8': '股票期权',
    '9': '金交所现货',
    'a': '金交所递延',
    'b': '金交所远期',
    'h': '现货期权'
}

option_type = {
    '0': '非期权',
    '1': '看涨',
    '2': '看跌'
}


@dataclass
class VtTickData(Base):
    """Tick 行情数据类, 来源为交易所推送的行情切片"""
    symbol = ""  # 合约代码
    exchange = ""  # 交易所代码
    vtSymbol = ""  # 合约代码.交易所代码

    lastPrice = 0.0  # 最新成交价
    lastVolume = 0  # 最新成交量
    volume = 0  # 今天总成交量
    openInterest = 0  # 持仓量
    time = ""  # 时间 11:20:56.5
    date = ""  # 日期 20151009
    datetime: DateTimeType = None  # 合约时间

    openPrice = 0.0  # 今日开盘价
    highPrice = 0.0  # 今日最高价
    lowPrice = 0.0  # 今日最低价
    preClosePrice = 0.0  # 昨收盘价
    PreSettlementPrice = 0.0  # 昨结算价

    upperLimit = 0.0  # 涨停价
    lowerLimit = 0.0  # 跌停价

    turnover = 0.0  # 成交额

    bidPrice1 = 0.0
    bidPrice2 = 0.0
    bidPrice3 = 0.0
    bidPrice4 = 0.0
    bidPrice5 = 0.0

    askPrice1 = 0.0
    askPrice2 = 0.0
    askPrice3 = 0.0
    askPrice4 = 0.0
    askPrice5 = 0.0

    bidVolume1 = 0
    bidVolume2 = 0
    bidVolume3 = 0
    bidVolume4 = 0
    bidVolume5 = 0

    askVolume1 = 0
    askVolume2 = 0
    askVolume3 = 0
    askVolume4 = 0
    askVolume5 = 0


@dataclass
class TickData(VtTickData):
    """带最新成交量的最新 Tick 数据"""

    _cache_volume = 0  # 缓存总成交量
    _cache_time = ""  # 缓存时间
    _last_volume = 0  # 缓存最新成交量

    @property
    def last_volume(self) -> int:
        """最新成交量"""
        if self.time == TickData._cache_time:
            return TickData._last_volume

        last_volume: int = self.volume - TickData._cache_volume

        if not TickData._cache_volume:
            last_volume = 0

        TickData._cache_volume = self.volume
        TickData._cache_time = self.time
        TickData._last_volume = last_volume

        return last_volume

    def update(self, tick: "TickData") -> None:
        """更新 Tick 数据"""
        self.__dict__.update(tick.__dict__)


@dataclass
class TradeData(Base):
    """成交数据类, 来源为交易所推送的成交回报"""
    symbol = ""  # 合约代码
    exchange = ""  # 交易所代码
    vtSymbol = ""  # 合约代码.交易所代码

    tradeID = ""  # 成交编号
    vtTradeID = ""  # 成交编号

    orderID = ""  # 订单编号
    vtOrderID = ""  # 订单编号
    memo = "" # 订单备注

    # 成交相关
    direction = ""  # 成交方向
    offset = ""  # 成交开平仓
    price = 0.0  # 成交价格
    volume = 0  # 成交数量
    tradeTime = ""  # 成交时间

    commission = 0.0  # 手续费


class VtTradeData(TradeData):
    ...


@dataclass
class OrderData(Base):
    """订单数据类, 来源为交易所推送的委托回报"""
    symbol = ""  # 合约代码
    exchange = ""  # 交易所代码
    vtSymbol = ""  # 交易所代码

    orderID = ""  # 订单编号
    vtOrderID = ""  # 订单编号
    memo = "" # 订单备注

    # 报单相关
    direction = ""  # 报单方向
    offset = ""  # 报单开平仓
    price = 0.0  # 报单价格
    priceType = ""  # 报单价格
    totalVolume = 0  # 报单总数量
    tradedVolume = 0  # 报单成交数量
    status = ""  # 报单状态

    orderTime = ""  # 发单时间
    cancelTime = ""  # 撤单时间

    frontID = 0  # 前置机编号
    sessionID = 0  # 连接编号


class VtOrderData(OrderData):
    ...


@dataclass
class KLineData(Base):
    """K 线对象"""
    vtSymbol = ""  # vt系统代码
    symbol = ""  # 代码
    exchange = ""  # 交易所

    open = 0.0  # OHLC
    high = 0.0
    low = 0.0
    close = 0.0

    date = ""  # bar开始的时间，日期
    time = ""  # 时间
    datetime: DateTimeType = None  # python的datetime时间对象

    volume = 0  # 成交量
    openInterest = 0  # 持仓量


class VtBarData(KLineData):
    ...


@dataclass
class PositionData(Base):
    """
    持仓数据类
    ---
    此类并不参与实际代码执行，由于原数据返回为字典类型，这里的变量只是方便查看
    """
    BrokerID = "" # 经纪公司编号
    ExchangeID = "" # 交易所代码
    InvestorID = "" # 投资者编号
    InstrumentID = "" # 合约代码
    Direction = "" # 持仓方向 多, 空
    HedgeFlag = "" # 投机套保方向：1 - 投机，2 - 套利，3 - 套保，4 - 做市商，5 - 备兑
    Position = 0 # 总持仓量
    FrozenPosition = 0 # 开仓冻结持仓
    FrozenClosing = 0 # 平仓冻结持仓
    YdFrozenClosing = 0 # 昨持仓平仓冻结持仓
    YdPositionClose = 0 # 昨持仓可平仓数量(包括平仓冻结持仓)
    OpenVolume = 0 # 今日开仓数量(不包括冻结)
    CloseVolume = 0 # 今日平仓数量(包括昨持仓的平仓,不包括冻结)
    StrikeFrozenPosition = 0 # 执行冻结持仓
    AbandonFrozenPosition = 0 # 放弃执行冻结持仓
    PositionCost = 0.0 # 总持仓成本
    YdPositionCost = 0.0 # 初始昨日持仓成本(当日不变)
    CloseProfit = 0.0 # 平仓盈亏
    PositionProfit = 0.0 # 持仓盈亏
    OpenAvgPrice = 0.0 # 开仓均价
    PositionAvgPrice = 0.0 # 持仓均价
    CloseAvailable = 0 # 当前可平
    PositionClose = 0 # 总持仓可平仓数量(包括平仓冻结持仓)


class VtPositionData(PositionData):
    ...


@dataclass
class AccountData(Base):
    """账户数据类"""
    query_time: DateTimeType = None  # 数据查询时间
    investor: str = ""  # 投资者编号
    accountID: str = ""  # 资金帐号

    preBalance: float = 0.0  # 昨日账户结算净值
    balance: float = 0.0  # 账户净值

    available: float = 0.0  # 可用资金
    pre_available: float = 0.0  # 上日可用资金

    closeProfit: float = 0.0  # 平仓盈亏
    positionProfit: float = 0.0  # 持仓盈亏
    dynamic_rights: float = 0.0  # 动态权益

    commission: float = 0.0  # 手续费

    frozen_margin: float = 0.0  # 冻结的保证金
    margin: float = 0.0  # 占用保证金

    risk: float = 0.0  # 风险度

    deposit: float = 0.0  # 入金金额
    withdraw: float = 0.0  # 出金金额


@dataclass
class ContractData(Base):
    """合约详细信息类"""
    symbol = ""  # 代码
    exchange = ""  # 交易所代码
    vtSymbol = ""  # 合约代码.交易所代码
    name = ""  # 合约中文名

    productClass = ""  # 合约类型
    size = 0  # 合约大小（合约乘数）
    priceTick = 0.0  # 合约最小价格TICK
    min_limit_order_volume = 0 # 最小下单量
    max_limit_order_volume = 0  # 最大下单量
    expire_date = "" # 合约到期日

    # 期权相关
    strikePrice = 0.0  # 期权行权价
    underlyingSymbol = ""  # 标的物合约代码
    optionType = ""  # 期权类型


class VtContractData(ContractData):
    ...


@dataclass
class ContractStatusData(Base):
    """合约状态类"""
    symbol = ""  # 代码
    exchange = ""  # 交易所代码
    status = ""  # 报单状态


class VtContractStatusData(ContractStatusData):
    ...


def importStrategy(path):
    """导入 Python 策略"""
    errCode = ""
    try:
        file_name: str = os.path.basename(path)
        model_name = os.path.splitext(file_name)[0]
        machinery.SourceFileLoader(model_name, path).load_module()
        if not hasattr(sys.modules[model_name], model_name):
            ctaEngine.writeLog(f'策略文件 {file_name} 中没有 {model_name} 类, 请检查')
            return 'error', None
        return errCode, getattr(sys.modules[model_name], model_name)
    except:
        errCode = traceback.format_exc()
        errCode = errCode.replace('\n', '\r\n')
        return errCode, None


def safeDatetime(timeStr: str) -> DateTimeType:
    """无限易使用此函数将时间字符串转为 DateTime 对象"""
    __format = "%Y%m%d %H:%M:%S.%f"
    if all(timeStr.split(" ")):
        return datetime.datetime.strptime(timeStr, __format)
    _today = datetime.date.today().strftime('%Y%m%d')
    return datetime.datetime.strptime(f"{_today}{timeStr}", __format)


def safeCall(pyFunc, pyArgs=()):
    """创建策略实例
    pyFunc: onStop, onInit等各种方法的对象
    pyRes: 策略参数的对象
    pyArgs: 一排() + tick对象
    """
    try:
        pyRes = pyFunc(*pyArgs)
        return pyRes
    except:
        errCode = '\r\n'.join([str(pyFunc), traceback.format_exc()])
        errCode = errCode.replace('\n', '\r\n')
        ctaEngine.writeLog(errCode)
        return 'error'
