# encoding: UTF-8

"""
期权定价计算
用于展示：期权用合成期货做标的计算出的理论价格差异曲线

计算原理：
自定义 iv 使用 BS 公式，计算出标的为期货的理论价格和实际价格做对比

图形说明：
上部：期权 K 线
中部：期权成交量
下部：期权实际收盘价和期权使用 BS 公式计算出的理论价

注意事项：
1. 期权种类在 T 型报价 - 品种栏位处查看
2. 对于非价外合约，当其价格不存在 iv 时，算出来的值不准确，仅作为参考
3. 部分新增合约，由于没有历史数据，无法查看，如果要想查看，需要先看下行情线图，是否有下载相应时间的历史数据， call 和 put 都要.
4. ETF 期权和股票期权不适用

last update: 2024-01-16 10:30:41
"""


import time
from datetime import datetime
from traceback import format_exc
from typing import Callable, Dict

import ctaEngine  # type:ignore
from ctaTemplate import BarManager, CtaTemplate, KLWidget
from option_template import Option
from vtObject import TickData, KLineData


class Demo_OptionBSPrice(CtaTemplate):
    """示例_计算商品期权和股指期权理论价格和实际价格差异曲线"""

    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'exchange': '交易所',
            'instrument': '期权合约代码',
            'product': '期权品种',
            'rf': '风险利率',
            'nMin': 'K线分钟',
            'days_of_year': '一年天数',
            'iv': '自定义波动率'
        }
        
        # 变量映射表
        self.varMap = {
            'days_of_year': '每年天数',
        }

        self.instrument = ''  # 合约名
        self.exchange = ''  # 交易所
        self.product = ''  # 品种，详情见 T 型报价品种栏位

        self.widgetClass = KLWidget  # 图形类
        self.widget: KLWidget = None

        self.nMin = 1  # 周期
        self.rf = 0.02  # 无风险利率
        self.days_of_year = 365 # 每年天数

        self.theoretical_price = 0  # 期权理论价格
        self.close = 0.0  # 收盘价
        self.opposite_price = 0.0  # 同一执行价另一期权价格

        self.option_symbol = ''  # 同一执行价另一期权合约名
        self.underlying_symbol = ''  # 标的合约
        self.expire_date = ''  # 到期日
        self.k = 0.0  # 执行价
        self.option_type = ''  # 期权类型
        self.underlying_price = 0.0  # 标的收盘价
        self.synthetic_futures_price = 0.0  # 合成期货价格

        self.trading = False  # 交易状态
        
        self.bm: Dict[str, BarManager] = {}

        self.iv = 0.15  # 自定义的波动率
        self.mainSigs = []  # 主图显示内容
        self.subSigs = ['bs_price', 'close']  # 副图显示内容

    def on_bar(self, bar: KLineData) -> None:
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        # 记录数据
        self.bm[bar.symbol].updateBar(bar)
        
    def onInit(self) -> None:
        super().onInit()
        self.getGui()
    
    def on_xmin_bar(self, bar: KLineData) -> None:
        # 记录数据
        if bar.symbol == self.instrument:
            self.bar = bar
            self.close = bar.close

            if all([self.close, self.opposite_price, self.underlying_price]):
                c = self.close if self.option_type == 'Call' else self.opposite_price
                p = self.opposite_price if self.option_type == 'Call' else self.close
                self.synthetic_futures_price = c - p + self.k

                # 计算指标
                self.get_signal(bar)

            # 发出状态更新事件
            if self.widget and self.bar:
                self.widget.recv_kline({
                    'bar': self.bar,
                    'sig': 0,
                    'bs_price': self.theoretical_price,
                    'close': self.close
                })

            if self.trading:
                self.putEvent()

        elif bar.symbol == self.option_symbol:
            self.opposite_price = bar.close

        elif bar.symbol == self.underlying_symbol:
            self.underlying_price = bar.close

    def time_tango(self, dates: str) -> datetime:
        """时间格式"""
        return datetime.strptime(dates, "%Y%m%d")

    def get_signal(self, bar: KLineData) -> None:
        """BS公式计算定价"""
        self.t = 1.0 * (self.time_tango(self.expire_date) - self.time_tango(bar.date)).days / self.days_of_year

        option_class = Option(
            option_type=self.option_type,
            underlying_price=self.synthetic_futures_price,
            k=self.k,
            t=self.t,
            r=self.rf,
            market_price=bar.close,
            dividend_rate=0.0,
            sigma=self.iv
        )

        self.theoretical_price = option_class.bs_price()

    def get_contract(self) -> None:
        """整理合约信息"""
        contract: dict = ctaEngine.getInstrument(self.exchange, self.instrument)

        self.option_type = 'Call' if contract['OptionsType']== '1' else 'Put'
        self.k = contract['StrikePrice']
        self.expire_date = contract['ExpireDate']
        opposite_option_type = '2' if contract['OptionsType'] == '1' else '1'
        
        self.underlying_symbol = contract['UnderlyingInstrID']
        contract_raw = ctaEngine.getInstListByExchAndProduct(str(self.exchange), str(self.product))
        
        self.option_symbol = next((
            i['Instrument']
            for i in contract_raw
            if i['StrikePrice'] == self.k
               and i['OptionsType'] == opposite_option_type
               and i['UnderlyingInstrID'] == self.underlying_symbol
        ), None)

    def onTick(self, tick: TickData) -> None:
        # 过滤涨跌停和集合竞价
        if tick.lastPrice == 0 or tick.askPrice1 == 0 or tick.bidPrice1 == 0:
            return
        
        super().onTick(tick)

        self.bm[tick.symbol].updateTick(tick)

    def onStart(self):
        self.output(f'{self.name} 策略启动')

        self.get_contract()
        self.exchangeList = [self.exchange] * 3
        self.symbolList = [self.instrument, self.option_symbol, self.underlying_symbol]

        for i in self.symbolList:
            self.bm[i] = BarManager(self.on_bar, self.nMin, self.on_xmin_bar)

        self.load_history_data(1, self.symbolList, self.exchangeList, qt_gui=True)

        self.subSymbol()
        self.trading = True
        
        if self.widget and self.bar:
            self.widget.load_data_signal.emit()
    
    def load_history_data(
        self,
        days: int,
        symbol: str = None,
        exchange: str = None,
        func: Callable[[KLineData], None] = None,
        qt_gui: bool = False
    ) -> None:
        """多合约，载入 1 分钟 K 线"""
        if qt_gui:
            for _ in range(5):
                #: 如果没有 K 线 UI 没加载全, 会导致线图为空
                if not self.__class__.qtsp:
                    self.output('QT 为空')
                    time.sleep(0.5)

        bars_list = []
        symbol = symbol or self.instrument
        exchange = exchange or self.exchange

        symbolList = symbol if isinstance(symbol, list) else [symbol]
        exchangeList = exchange if isinstance(exchange, list) else [exchange]
        func = func or self.on_bar

        for symbol, exchange in zip(symbolList, exchangeList):

            if not all([symbol, exchange]):
                raise TypeError('错误：交易所或合约为空！')

            # 将天数切割为 3 天以内的单元
            time_gap = 3
            divisor = int(days / time_gap)
            days_list = [time_gap] * divisor

            if (remainder := days % time_gap) != 0:
                days_list.insert(0, remainder)

            # 分批次把历史数据取到本地，然后统一下载

            now_time = datetime.now()
            start_date = now_time.strftime('%Y%m%d')
            start_time = now_time.strftime('%H:%M:%S')

            for _days in days_list:
                bars: list = ctaEngine.getKLineData(symbol, exchange, start_date, _days, 0, start_time, 1)
                if not bars:
                    self.output(f'{symbol}没有数据，已跳过，若无限易行情线图有数据，请检查参数填写是否错误')
                    return
                bars.reverse()
                bars_list.extend(bars)
                start_date = bars[-1].get('date')
                start_time = bars[-1].get('time')

        bars_list = sorted(bars_list, key=lambda x: x['datetime'])

        # 处理数据
        try:
            for _bar in self.deleteDuplicate(bars_list):

                bar = KLineData()
                bar.__dict__.update(_bar)
                func(bar)
        except Exception as e:
            self.output(format_exc())
            self.output(f'历史数据获取失败，使用实盘数据初始化 {e}')
