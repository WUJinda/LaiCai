"""
用于计算 VIX 指数

注意：
1. 历史数据较多，需要缓存一段时间，具体时长与以下内容有关：
    A.填写的下载历史数据周期
    B.自己电脑性能

参数填写：
    A. 股票期权和需要填写标的代码，其他期权直接填 0 就行
    B. 品种: 填写 T 型报中的品种,商品期权填商品期权代码 e.g. CF

误差说明:
1. 由于没有历史的 Tick 数据，无法获取昨结价，所有历史价格使用历史分钟线最新价，可能导致：
    A. 交易不频繁的品种（缺失数据的品种会有提示），计算可能不准确.
    B. 部分品种数据不足，无法计算。
    C. 出现历史信号和最新 TICK 数据计算出的结果不一致（因为用 TICK 的话，每个合约都最少有一个昨结价）
2. 如果使用历史回放站点，可能会出现数据更新时间不正确的问题

last update: 2024-01-16 10:30:31
"""

import threading
import time
from datetime import datetime
from traceback import format_exc
from typing import Dict

import ctaEngine  # type: ignore
import numpy as np
import pandas as pd

from ctaTemplate import ArrayManager, BarManager, CtaTemplate, KLWidget
from vtObject import KLineData


class Demo_OptionVIX(CtaTemplate):
    """绘制 VIX 指数趋势图像"""
    def __init__(self):
        """初始化"""
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'minutes': 'K线周期',
            'exchange': '交易所',
            'underlying_id': '标的代码（除了股票期权都填 0）',
            'product': '品种',
            'period':'历史数据长度（天）'
        }

        # 变量映射表
        self.varMap = {
            'vix': '当前 VIX 指数',
            'near_contract_expire': '近月合约到期日',
            'near_contract_num': '近月合约数',
            'next_contract_expire': '远月合约到期日',
            'next_contract_num': '远月合约数'
        }

        # 时间变量
        self.t_year = 525600  # 年分钟数
        self.t_month = 43200  # 月分钟数
        self.t1 = 0  # 近月合约剩余时间（年化）
        self.nt1 = 0  # 近月合约剩余分钟数
        self.t2 = 0  # 远月合约剩余时间（年化）
        self.nt2 = 0  # 远月合约剩余分钟数
        self.minutes = 1  # 合成的 VIX 指数的分钟数

        # 自填变量
        self.exchange = ''  # 交易所
        self.product = ''  # 品种
        self.period = 1  # 历史数据量
        self.r = 0.02  # 无风险利率

        # 控制变量
        self.contract_tick_update = False  # 控制 Tick 更新
        self.start_vix = False  # 控制 VIX 计算
        self.update_underlying = False  # 传送标的数据更新

        # 期权
        self.option_contracts = []  # 所有期权合约名
        self.next_contract_expire = '19900101'  # 远月合约到期日
        self.near_contract_num = 0  # 远月合约数
        self.near_contract_expire = '19900101'  # 近月合约到期日
        self.next_contract_num = 0  # 近月合约数
        self.underlying_contracts_list = []  # 所有标的合约列表
        self.underlying_id = '0'  # 初始标的合约，用于筛选 ETF 期权合约
        self.underlying_near = ''  # 近月标的
        self.underlying_next = ''  # 远月标的

        # 综合
        self.bm: Dict[str, BarManager] = {}
        self.am: Dict[str, ArrayManager] = {}
        self.symbolList = []  # 所有合约代码，包括期权和标的
        self.vix = 0.0  # VIX 指数
        self.vx = VixArray(self, size=100)  # 专用于计算 VIX 的类

        # 图形界面类
        self.widgetClass = KLWidget
        self.widget = None
        self.mainSigs = []
        self.subSigs = ['vix']

    def onInit(self) -> None:
        super().onInit()
        self.getGui()

    def onStart(self) -> None:
        self.output('策略启动')
        self.contract_tick_update = False
        self.vx = VixArray(self, size=100)
        self.start_vix = False
        self.update_underlying = False

        self.get_contract_info()
        
        # 每个合约单独合成多分钟 K 线
        for s in self.symbolList:
            self.bm[s] = BarManager(self.on_bar, self.minutes, self.on_xmin_bar)

        # 下载期权历史数据
        self.exchangeList = [self.exchange] * len(self.option_contracts)
        self.load_history_data(self.period + 1, self.option_contracts, self.exchangeList)

        self.contract_tick_update = True
        self.subSymbol(self.option_contracts)

        if self.underlying_near != self.underlying_next:
            self.load_history_data(self.period, self.underlying_next)

        self.start_vix = True
        self.load_history_data(self.period, self.underlying_near)

        self.update_underlying = True
        self.trading = True

        self.subSymbol(self.underlying_contracts_list)

        if self.widget is not None and self.bar is not None:
            self.widget.load_data_signal.emit()

    def subSymbol(self, symbolList):
        """订阅指定合约列表"""
        for symbol in symbolList:
            ctaEngine.subMarketData({
                'sid': self,
                'InstrumentID': str(symbol),
                'ExchangeID': str(self.exchange)
            })

    def on_bar(self, bar):
        # 每个合约的 bm 不一样，以免出现 bar.high 的问题以及 bar.symbol 的问题
        self.bm[bar.symbol].updateBar(bar)

        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

    def on_xmin_bar(self, bar):
        self.vx.update_bar(bar)

        if self.start_vix:
            if bar.symbol == self.underlying_near:
                self.bar = bar
                self.vx.VIX_calculate()
                self.vix = self.vx.vix

                self.putEvent()
                if self.widget and self.bar:
                    self.widget.recv_kline({
                        'bar': self.bar,
                        'sig': 0,
                        'vix': self.vix
                    })

    def setParam(self, setting):
        super().setParam(setting)
        self.underlying_id = str(self.underlying_id)

    def onTick(self, tick):
        self.bm[tick.symbol].updateTick(tick)

    def load_history_data(self, days: int, symbol=None, exchange=None, func=None, qt_gui=False) -> None:
        """载入 1 分钟 K 线，和父类不一样，不能直接继承"""
        if qt_gui:
            for _ in range(5):
                #: 如果没有 K 线 UI 没加载全, 会导致线图为空
                if not self.__class__.qtsp:
                    self.output('QT 为空')
                    time.sleep(0.5)

        bars_list = []
        symbol = symbol or self.vtSymbol
        exchange = exchange or self.exchange

        check_symbol_list = isinstance(symbol, list)
        
        symbolList = symbol if check_symbol_list else [symbol]
        exchangeList = exchange if isinstance(exchange, list) else [exchange]
        func = func or self.on_bar
        count = 0

        for symbol, exchange in zip(symbolList, exchangeList):
            
            if not all([symbol, exchange]):
                raise TypeError('错误：交易所或合约为空！')
            
            # 将天数切割为 3 天以内的单元
            time_gap = 3
            divisor = int(days / time_gap)
            days_list = [time_gap] * divisor
            if (remainder := days % time_gap) != 0:
                days_list.insert(0, remainder)

            now_time = datetime.now()
            start_date = now_time.strftime('%Y%m%d')
            start_time = now_time.strftime('%H:%M:%S')

            for _days in days_list:
                bars: list = ctaEngine.getKLineData(symbol, exchange, start_date, _days, 0, start_time, 1)
                if not bars:
                    self.output(f'{symbol} 合约在所选周期内没有分钟线数据')
                    continue
                bars.reverse()
                bars_list.extend(bars)
                start_date = bars[-1].get('date')
                start_time = bars[-1].get('time')
            count += 1
            if not (count / len(symbolList) * 100) % 10 and not check_symbol_list:
                self.output(f'--------------------------\n目前历史数据下载进度{count / len(symbolList) * 100}')

        bars_list = sorted(bars_list, key=lambda x: x['datetime'])
        if not bars_list:
            self.output('所有合约在周期内没有数据')
            self.onStop()

        # 处理数据
        try:
            for _bar in self.deleteDuplicate(bars_list):
                bar = KLineData()
                bar.__dict__.update(_bar)
                func(bar)

        except Exception as e:
            self.output(format_exc())
            self.output(f'历史数据获取失败，使用实盘数据初始化 {e}')

    def get_contract_info(self):
        """获取期权合约相关信息"""
        # 获取所有合约
        total_option = ctaEngine.getInstListByExchAndProduct(str(self.exchange), str(self.product))
        
        valid_classes = {'2', '8', 'h'}
        total_option = pd.DataFrame([i for i in total_option if i['ProductClass'] in valid_classes])

        if total_option.empty:
            self.pause_strategy()
            raise Exception('品种输入有误，未搜索到数据')

        # 选出近月和远月时间
        time_list = total_option['ExpireDate']
        self.expire(time_list)

        # 取出近月合约，取出远月合约
        near_filter = total_option['ExpireDate'] == self.near_contract_expire
        next_filter = total_option['ExpireDate'] == self.next_contract_expire
        underlying_filter = total_option['UnderlyingInstrID'] == self.underlying_id

        stock_option_judge = self.underlying_id != '0'  # 判断是否为股票期权，股票期权品种名都为 ETF_O 所以需要自己填标的筛选

        near_options = total_option[near_filter & underlying_filter] if stock_option_judge else total_option[near_filter]
        near_call_options = near_options[near_options['OptionsType'] == '1']

        near_put_options = near_options[near_options['OptionsType'] == '2'] 

        next_options = total_option[next_filter & underlying_filter] if stock_option_judge else total_option[next_filter]
        next_call_options = next_options[next_options['OptionsType'] == '1']
        next_put_options = next_options[next_options['OptionsType'] == '2'] 
        near_contracts_list = near_options['Instrument'].tolist()
        next_contracts_list = next_options['Instrument'].tolist()
        self.option_contracts = next_contracts_list + near_contracts_list

        self.vx.contract_info(near_call_options, near_put_options, next_call_options, next_put_options)

        self.underlying_near = near_options['UnderlyingInstrID'].iloc[0]
        self.underlying_next = next_options['UnderlyingInstrID'].iloc[0]

        # 处理需要订阅的合约列表
        self.underlying_contracts_list = list(pd.Series([self.underlying_near, self.underlying_next]).unique())
        self.symbolList = self.option_contracts + self.underlying_contracts_list

        # 整理总结合约数据
        self.near_contract_num = len(near_contracts_list)
        self.next_contract_num = len(next_contracts_list)

        if self.underlying_id == '0':
            self.output(f'--------------------------\n近月标的合约: {self.underlying_near}')
            self.output(f'--------------------------\n近月标的合约: {self.underlying_next}')
        else:
            self.output(f'--------------------------\n标的合约: {self.underlying_id}')

        self.putEvent()

    def time_tango(self, dates):
        """时间格式"""
        return datetime.strptime('{}'.format(dates), '%Y%m%d')

    def expire(self, time_list: list):
        """处理时间列表，找出近月和远月"""
        # 同一个交易所，所有品种到期日序列相同
        now = datetime.now()
        time_set = time_list.unique()
        time_set.sort()

        t0 = 1.0 * (self.time_tango(time_set[0]) - now).days
        if t0 <= 7:
            self.near_contract_expire = time_set[1]
            self.next_contract_expire = time_set[2]
        else:
            self.near_contract_expire = time_set[0]
            self.next_contract_expire = time_set[1]

        # 定义时间变量
        t1_other = 1.0 * (self.time_tango(self.near_contract_expire) - now).days * 1440
        t2_other = 1.0 * (self.time_tango(self.next_contract_expire) - now).days * 1440
        t_current = 60 * (23 - now.hour) + now.minute
        t_settlement = 9.5 * 60

        self.t1 = (t1_other + t_current + t_settlement) / self.t_year
        self.nt1 = (t1_other + t_current + t_settlement)
        self.t2 = (t2_other + t_current + t_settlement) / self.t_year
        self.nt2 = (t2_other + t_current + t_settlement)


class VixArray(ArrayManager):
    """
    VIX 专用计算类
    """

    def __init__(self, strategy, size=100, maxsize=None, bars=None):
        """Constructor"""
        self.strategy = strategy

        option_columns = ['strike_price', 'call_symbol', 'call_price', 'put_symbol', 'put_price', 'call_put_diff']
        price_columns = ['strike_price', 'Price', 'call_put_diff']

        self.total_near_data = pd.DataFrame(columns=option_columns)
        self.near_price_data = pd.DataFrame(columns=price_columns)
        self.total_next_data = pd.DataFrame(columns=option_columns)
        self.next_price_data = pd.DataFrame(columns=price_columns)

        self.count = 0  # 缓存计数
        self.maxsize = size

        self.total_data = pd.DataFrame(columns=['Symbol', 'Time', 'Close'])

        self.near_sigma = 0.0
        self.next_sigma = 0.0

        # 用于保存最初有数据的合约列表，和每日的合约列表不一样，每日的会删掉没有数据的合约
        self.near_call_symbol = []
        self.near_put_symbol = []
        self.next_call_symbol = []
        self.next_put_symbol = []

        self.near_strike_price_list = []
        self.next_strike_price_list = []
        self.underlying_time = None  # 标的合约的更新时间

        self.vix = 0.0  # VIX 指数
        self.VIX_array = np.zeros(self.maxsize)

    def contract_info(self, near_call_options, near_put_options, next_call_options, next_put_options):
        """更新合约信息"""
        self.near_call_symbol = near_call_options['Instrument'].tolist()
        self.near_put_symbol = near_put_options['Instrument'].tolist()

        self.next_call_symbol = next_call_options['Instrument'].tolist()
        self.next_put_symbol =  next_put_options['Instrument'].tolist()

        self.near_strike_price_list = near_call_options['StrikePrice'].tolist()
        self.next_strike_price_list = next_call_options['StrikePrice'].tolist()

    def update_contract_info(self):
        # 重新初始化
        self.total_near_data.drop(self.total_near_data.index, inplace=True)
        self.near_price_data.drop(self.near_price_data.index, inplace=True)
        self.total_next_data.drop(self.total_next_data.index, inplace=True)
        self.next_price_data.drop(self.next_price_data.index, inplace=True)

        self.total_near_data['call_symbol'] = self.near_call_symbol
        self.total_near_data['strike_price'] = self.near_strike_price_list
        self.total_near_data['put_symbol'] = self.near_put_symbol
        self.total_near_data = self.total_near_data.sort_values("strike_price")

        self.total_next_data['call_symbol'] = self.next_call_symbol

        self.total_next_data['strike_price'] = self.next_strike_price_list
        self.total_next_data['put_symbol'] = self.next_put_symbol
        self.total_next_data = self.total_next_data.sort_values("strike_price")

        self.near_price_data['strike_price'] = self.total_near_data['strike_price'].tolist()
        self.next_price_data['strike_price'] = self.total_next_data['strike_price'].tolist()

    def update_bar(self, bar):
        if type(bar) is str:
            bar.datetime = datetime.datetime.strptime(self.bar.datetime, '%Y-%m-%d %H:%M:%S')

        if bar.symbol in self.strategy.option_contracts:
            close_data = [{'Symbol': str(bar.symbol), 'Time': bar.datetime, 'Close': bar.close}]
            self.total_data = self.total_data.append(close_data, ignore_index=True)
            if self.strategy.contract_tick_update:
                self.update_tick(bar)

        if bar.symbol == self.strategy.underlying_near:
            self.underlying_time = bar.datetime

            if not self.strategy.update_underlying:
                self.init_price()

    def update_tick(self, bar):
        """下载完历史数据之后，根据 Tick 数据更新"""
        if bar.symbol in self.total_near_data['call_symbol'].tolist():
            check_symbol = self.total_near_data['call_symbol']==bar.symbol
            self.total_near_data['call_price'].loc[check_symbol] = bar.close
        elif bar.symbol in self.total_near_data['put_symbol'].tolist():
            check_symbol = self.total_near_data['put_symbol']==bar.symbol
            self.total_near_data['put_price'].loc[check_symbol] = bar.close
        elif bar.symbol in self.total_next_data['call_symbol'].tolist():
            check_symbol = self.total_next_data['call_symbol']==bar.symbol
            self.total_next_data['call_price'].loc[check_symbol] = bar.close
        elif bar.symbol in self.total_next_data['put_symbol'].tolist():
            check_symbol = self.total_next_data['put_symbol']==bar.symbol
            self.total_next_data['put_price'].loc[check_symbol] = bar.close
        else:
            self.strategy.output(f'新增此前无数据合约 {bar.symbol}')
            self.init_price()  # 考虑新挂牌合约，重置序列

    def init_price(self):
        """价格数据初始化"""
        self.update_contract_info()

        def _update_price(_option_type, _expire_type):
            signal = _option_type + "_symbol"
            price_signal = _option_type + "_price"
            func = getattr(self, 'total_' + _expire_type + '_data')

            for contract in func[signal].tolist():
                init_data = self.total_data[self.total_data['Symbol'] == contract]

                if not init_data.empty:
                    check_symbol = func[signal] == contract

                    min_time = min(abs(self.underlying_time - init_data['Time']))
                    check_time = abs(self.underlying_time - init_data['Time']) == min_time

                    new_price = init_data[check_time]['Close'].values[0]
                    func[price_signal].loc[check_symbol] = new_price

        threads = []

        for option_type in ['call', 'put']:
            for expire_type in ['near', 'next']:
                thread = threading.Thread(target=_update_price, args=(option_type, expire_type,))
                thread.start()
                threads.append(thread)

        for thread in threads:
            thread.join()

    def data_calculate(self, expire_type):
        func = getattr(self, 'total_' + expire_type + '_data')
        price_func = getattr(self, expire_type + '_price_data')
        time_func = self.strategy.t1 if expire_type == 'near' else self.strategy.t2

        func['call_put_diff'] = abs(func['call_price'] - func['put_price'])

        func = func.dropna().reset_index(drop=True)
        func = func.drop(func[func['call_price'] == 0].index).reset_index(drop=True)
        func = func.drop(func[func['put_price'] == 0].index).reset_index(drop=True)
        
        min_diff_price = min(func['call_put_diff'])
        min_strike_price = func[func['call_put_diff'] == min_diff_price]['strike_price'].values[0]

        price_func['strike_price'] = func['strike_price']
        price_func['call_put_diff'] = func['call_put_diff']

        at_the__money = price_func['strike_price'] == min_strike_price
        at_the__money_call= func['call_price'][func['strike_price'] == min_strike_price].values[0]
        at_the__money_put = func['put_price'][func['strike_price'] == min_strike_price].values[0]

        out_the_money_put = price_func['strike_price'] < min_strike_price
        out_the_money_call = price_func['strike_price'] > min_strike_price

        price_func['Price'].loc[out_the_money_put] = func['put_price'][func['strike_price'] < min_strike_price]
        price_func['Price'].loc[at_the__money] = (at_the__money_call + at_the__money_put) / 2
        price_func['Price'].loc[out_the_money_call] = func['call_price'][func['strike_price'] > min_strike_price]

        price_func = price_func.dropna().reset_index(drop=True)
        future_price = min_strike_price + np.exp(self.strategy.r * time_func) * min_diff_price
        
        self.sigma_calculate(min_strike_price, expire_type, future_price, func, price_func, time_func)

    def sigma_calculate(self, min_strike_price, expire_type, future_price, func, price_func, time_func):
        contribution = 0
        r_t = np.exp(self.strategy.r * time_func)

        for i in range(0, len(price_func) - 1):
            if i == 0:
                d_strike_price = price_func['strike_price'][i + 1] - price_func['strike_price'][i]
                contribution += d_strike_price / price_func['strike_price'][i] ** 2 * r_t * price_func['Price'][i]
            elif i == len(price_func) - 1:
                d_strike_price = price_func['strike_price'][i] - price_func['strike_price'][i - 1]
                contribution += d_strike_price / price_func['strike_price'][i] ** 2 * r_t * price_func['Price'][i]
            else:
                d_strike_price = (price_func['strike_price'][i + 1] - price_func['strike_price'][i - 1]) / 2
                contribution += d_strike_price / price_func['strike_price'][i] ** 2 * r_t * price_func['Price'][i]

        sigma = 2 / time_func * contribution - (future_price / min_strike_price - 1) ** 2 / time_func

        if expire_type == 'near':
            self.near_sigma = sigma
            self.total_near_data = func
            self.near_price_data = price_func

        else:
            self.next_sigma = sigma 
            self.total_next_data = func
            self.next_price_data = price_func

    def VIX_calculate(self):
        """计算 VIX """
        for expire_type in ['near', 'next']:
            self.data_calculate(expire_type)

        dt = self.strategy.nt2 - self.strategy.nt1
        v1 = self.strategy.t1 * self.near_sigma * (self.strategy.nt2 - self.strategy.t_month) / dt
        v2 = self.strategy.t2 * self.next_sigma * (self.strategy.t_month - self.strategy.nt1) / dt

        self.vix = 100 * np.sqrt((v1 + v2) * self.strategy.t_year / self.strategy.t_month)

        self.VIX_array[0:self.maxsize - 1] = self.VIX_array[1:self.maxsize]
        self.VIX_array[-1] = self.vix
        self.count += 1

    @property
    def VIX_list(self):
        """获取 VIX 序列"""
        return self.VIX_array[-self.maxsize:]
    