# encoding: UTF-8

"""
期权希腊值或隐含波动率走势
用于展示：期权希腊值或隐含波动率走势
使用到的公式： BS 公式

股票期权不适用！

注意事项：
1. 期权种类在T型报价-品种栏位处查看。
2. 标的是合成期货。
3. 对于非价外合约，当其价格不存在 IV 时，算出来的值不准。
4. 部分新增合约，由于没有历史数据，无法查看，如果要想查看，需要先看下行情线图，是否有下载相应时间的历史数据， call 和 put 都要.
5. 由于只显示 2 位小数，所以 gamma 值乘以了 100。

last update: 2024-01-16 10:29:31
"""

import time
from datetime import datetime
from traceback import format_exc
from typing import Callable, Literal

import ctaEngine  # type: ignore
from ctaTemplate import BarManager, CtaTemplate, KLWidget
from option_template import Option
from vtObject import TickData, KLineData


class Demo_OptionGreeksCurve(CtaTemplate):
    """测试_商品期权和股指期权希腊值或隐含波动率走势曲线"""
    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'exchange': '交易所',
            'instrument': '期权合约代码',
            'product': '期权合约种类',
            'free_risk_rate': '风险利率',
            'nMin': 'K线分钟',
            'curve_type': '希腊值曲线类型',
            'days_of_year': '每年天数'
        }
        
        # 变量映射表
        self.varMap = {
            'days_of_year': '每年天数'
        }

        self.exchange = ''
        self.instrument = ''
        self.product = ''
        self.curve_type: Literal[
            'delta', 
            'gamma', 
            'vega', 
            'theta', 
            'rho',
            'iv'
        ] = ""

        self.days_of_year = 365  # 每年天数
        self.nMin = 1  # 周期
        self.free_risk_rate = 0.02  # 无风险利率

        self.close = 0.0  # 期权收盘价
        self.opposite_price = 0.0  # 同一执行价另一期权价格
        self.underlying_price = 0.0  # 标的收盘价
        self.synthetic_futures_price = 0.0  # 合成期货价格

        self.option_symbol = None  # 同一执行价另一期权合约名
        self.underlying_symbol = None  # 标的合约
        self.expire_date = None  # 到期日
        self.k = None  # 执行价
        self.option_type = None  # 期权类型
        
        self.trading = False

        self.delta = 0.0
        self.gamma = 0.0
        self.vega = 0.0
        self.theta = 0.0
        self.rho = 0.0
        self.iv = 0.0

        self.widgetClass = KLWidget
        self.widget: KLWidget = None

        self.bm = {}

        self.bar = None  # 绘图需要
        self.mainSigs = []  # 主图显示
        self.subSigs = [self.curve_type]


    def setParam(self, setting: dict) -> None:
        super().setParam(setting)
        self.curve_type = self.curve_type.lower()
        self.subSigs = [self.curve_type]

        if self.widget is not None:
            for indicator_name in self.widget.uiKLine.sub_indicator_plot_items:
                self.widget.uiKLine.pwOI.removeItem(
                    self.widget.uiKLine.sub_indicator_plot_items[indicator_name]
                )
                self.widget.uiKLine.sub_indicator_data  = {}
                self.widget.uiKLine.sub_indicator_plot_items = {}

    def on_bar(self, bar: KLineData) -> None:
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        # 记录数据
        self.bm[bar.symbol].updateBar(bar)
    
    def on_xmin_bar(self, bar: KLineData) -> None:
        # 记录数据

        if bar.symbol == self.underlying_symbol:
            self.underlying_price = bar.close

        elif bar.symbol == self.option_symbol:
            self.opposite_price = bar.close

        elif bar.symbol == self.instrument:
            self.bar = bar
            self.close = bar.close
            
            if all([self.close, self.opposite_price, self.underlying_price]):
                c = self.close if self.option_type == 'Call' else self.opposite_price
                p = self.opposite_price if self.option_type == 'Call' else self.close
                self.synthetic_futures_price = c - p + self.k
                
                self.get_indicator(bar)

                # 发出状态更新事件
                if self.widget and self.bar:
                    self.widget.recv_kline({
                        'bar': self.bar, 
                        'sig': 0, 
                        self.curve_type: getattr(self, self.curve_type)
                    })
                    
                if self.trading:
                    self.putEvent()
        
    def get_indicator(self, bar: KLineData) -> None:
        t = 1.0 * (self.time_tango(self.expire_date) - self.time_tango(bar.date)).days / self.days_of_year

        # 默认使用 BSM 进行计算，Option 类不填写 IV 的时候默认使用 BSM 二分法计算得出的 IV
        option_class = Option(
            option_type=self.option_type, 
            underlying_price=self.synthetic_futures_price, 
            k=self.k, 
            t=t, 
            r=self.free_risk_rate, 
            market_price=bar.close,
            dividend_rate=0
        )
        
        if self.curve_type == 'delta':
            self.delta = option_class.bs_delta()

        elif self.curve_type == 'gamma':
            self.gamma = option_class.bs_gamma() * 100

        elif self.curve_type == 'vega':
            self.vega = option_class.bs_vega() / 100
            
        elif self.curve_type == 'theta':
            self.theta = option_class.bs_theta()

        elif self.curve_type == 'rho':
            self.rho = option_class.bs_rho() / 100

        elif self.curve_type == 'iv':
            self.iv = option_class.bs_iv() * 100

    def time_tango(self, dates: str) -> datetime:
        """时间格式"""
        return datetime.strptime(dates, "%Y%m%d")

    def get_contract(self) -> None:
        """整理合约信息"""
        contract = ctaEngine.getInstrument(self.exchange, self.instrument)
        self.option_type = 'Call' if contract['OptionsType']== '1' else 'Put'
        self.k = contract['StrikePrice']
        self.expire_date = contract['ExpireDate']
        opposite_option_type = '2' if contract['OptionsType'] == '1' else '1'
        
        self.underlying_symbol =  contract['UnderlyingInstrID']
        contract_raw = ctaEngine.getInstListByExchAndProduct(str(self.exchange), str(self.product))

        self.option_symbol = next((
            i['Instrument']
            for i in contract_raw
            if i['StrikePrice'] == self.k
               and i['OptionsType'] == opposite_option_type
               and i['UnderlyingInstrID'] == self.underlying_symbol
        ), None)

    def onInit(self) -> None:
        super().onInit()
        self.getGui()
        self.subSigs = [self.curve_type]

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

        for symbol in self.symbolList:
            self.bm[symbol] = BarManager(self.on_bar, self.nMin, self.on_xmin_bar)

        try:
            # 当从加载实例中启动策略时, K 线图为空, 则需要把 qt_gui 设为 True
            self.load_history_data(1, self.symbolList, self.exchangeList, qt_gui=True)

        except (TypeError, ValueError) as e:
            self.output(format_exc())

        self.subSymbol()
        self.trading = True
        self.getGui()
        
        if self.widget is not None and self.bar is not None:
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

            # 分批次把历史数据取到本地，然后统一 load
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
