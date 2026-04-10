"""
海龟策略
其中唐奇安通道是通过日线，而不是日=分钟线。如果需要通过日线，需要修改
最后更新: 2023年8月20日 17:36:47
"""

import ctaEngine  # type: ignore
from ctaTemplate import ArrayManager, BarManager, CtaTemplate
from vtObject import KLineData, OrderData, TickData, TradeData


class Demo_TurtleTrading(CtaTemplate):
    """海龟策略"""

    def __init__(self):
        super().__init__()
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '合约',
            'chasing_price': '超价平仓 Tick 数'
        }

        # 变量映射表
        self.varMap = {
            'up20': '20日唐奇安通道上轨',
            'down10': '10日唐奇安通道下轨',
            'atr': 'atr',
            'unit': '交易单位',
            'multiple': '合约单位',
            'total_net': '动态权益',
            'tick_price': '当前价格'
        }

        self.vtSymbol = ''
        self.exchange = ''
        self.period = 1

        self.am = ArrayManager(10)
        self.am_day = ArrayManager(30)
        self.bm = BarManager(self.on_bar, self.period, self.on_xmin_bar)
        self.order_count = 0
        self.orderID = {}

        self.up20 = 0
        self.up10 = 0
        self.down20 = 0
        self.down10 = 0

        self.unit = 0.0
        self.max_limit_order_volume = 0  # 最大下单手数
        self.min_limit_order_volume = 0  # 最小下单手数
        self.price_tick = 0.0  # 合约最小价格TICK
        self.chasing_price = 10  # 追单TICK数

        self.multiple = 0.0  # 合约乘数
        self.total_net = 0.0  # 动态权益
        self.atr = 0.0
        self.tick = TickData
        self.tick_price = 0.0  # 当前最新价
        self.price = 0.0  # 前次开仓价格

    def exec_signal(self) -> None:
        if not self.trading:
            return

        # 挂单未成交
        for i in range(self.order_count):
            if self.orderID[str(i)]:
                self.cancelOrder(self.orderID[str(i)])

        position = self.get_position(self.vtSymbol)

        self.get_unit()

        if position.net_position == 0:
            if self.tick_price > self.up20:
                self.orderID[str(self.order_count)] = self.buy(
                    price=self.tick_price,
                    volume=self.unit,
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    memo=str(self.order_count)
                )

                self.order_count += 1

                self.output(
                    f"{self.vtSymbol} 当前价 {self.tick_price} > 唐奇安通道上轨 {self.up20}, "
                    f"买入 1 个 Unit (持多仓): {self.unit} 手")

            elif self.tick_price < self.down10:
                self.orderID[str(self.order_count)] = self.short(
                    price=self.tick_price,
                    volume=self.unit,
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    memo=str(self.order_count)
                )

                self.order_count += 1
                self.output(
                    f"{self.vtSymbol} 当前价 {self.tick_price} < 唐奇安通道下轨 {self.down10}，"
                    f"卖出 1 个 Unit (持空仓): {self.unit} 手")

        elif position.net_position > 0:
            if cost := self.get_investor_cost(self.vtSymbol):
                self.price = [item for item in cost if item["direction"] == "LONG"][0]['open_avg_price']

            if self.tick_price >= (self.price + 0.5 * self.atr):
                self.orderID[str(self.order_count)] = self.buy(
                    price=self.tick_price,
                    volume=self.unit,
                    memo=str(self.order_count)
                )

                self.order_count += 1
                self.output(f"{self.vtSymbol} 加仓: 加 1 个 Unit {self.unit} 的多仓")

            elif self.tick_price <= self.down10:
                self.close_position()

        else:  # 持空单
            if cost := self.get_investor_cost(self.vtSymbol):
                self.price = [item for item in cost if item["direction"] == "SHORT"][0]['open_avg_price']

            if self.tick_price <= (self.price - 0.5 * self.atr):
                # 加仓策略: 如果是空仓且行情最新价在上一次建仓（或者加仓）的基础上又下跌了0.5N，就再加一个Unit的空仓

                self.orderID[str(self.order_count)] = self.short(
                    price=self.tick_price,
                    volume=self.unit,
                    memo=str(self.order_count)
                )

                self.order_count += 1
                self.output(f"{self.vtSymbol} 加仓: 加 1 个 Unit {self.unit} 的空仓")

            elif self.tick_price >= (self.price + 2 * self.atr) and self.tick_price >= self.up10:
                # 止损策略: 如果是空仓且行情最新价在上一次建仓（或者加仓）的基础上又上涨了2N，就平仓止损
                # 止盈策略: 如果是空仓且行情最新价升破了10日唐奇安通道的上轨，就清空所有头寸结束策略,离场

                self.close_position()

    def close_position(self) -> None:
        """全部平仓"""
        position = self.get_position(self.vtSymbol)

        long_position = position.long.position
        short_position = position.long.position

        sell_price = self.tick_price - self.chasing_price * self.price_tick
        buy_price = self.tick_price + self.chasing_price * self.price_tick

        if long_position:
            num = round(long_position / self.max_limit_order_volume - 0.5)

            for j in range(num+1):
                k = -num if j < 1 else 1
                order_position = max(0, 1-j) * long_position + k * self.max_limit_order_volume
                self.orderID[str(self.order_count)] = self.auto_close_position(
                    price=sell_price,
                    volume=order_position,
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    order_direction="sell",
                    memo=str(self.order_count)
                )

            self.order_count += 1

        if short_position:
            num = round(short_position / self.max_limit_order_volume - 0.5)

            for j in range(num+1):
                k = -num if j < 1 else 1
                order_position = max(0, 1 - j) * short_position + k * self.max_limit_order_volume
                self.orderID[str(self.order_count)] = self.auto_close_position(
                    price=buy_price,
                    volume=order_position,
                    symbol=self.vtSymbol,
                    exchange=self.exchange,
                    order_direction="buy",
                    memo=str(self.order_count)
                )
                self.order_count += 1

        tip_text = f"{self.vtSymbol} 清空持仓: 卖出 {long_position} 买入 {short_position}"
        self.output(tip_text)

    def onOrder(self, order: OrderData, log: bool = False) -> None:
        """收到委托变化推送，发单成功也算委托变化"""
        if not order:
            return

        offset = order.offset
        status = order.status

        if status == '已撤销':
            self.orderID[order.memo] = None
        elif status == '全部成交' or status == '部成部撤':
            self.orderID[order.memo] = None
        if log:
            self.output(' '.join([offset, status]))

    def onStart(self) -> None:
        self.trading: bool = False
        self.symbolList = self.vtSymbol.split(';')
        self.exchangeList = self.exchange.split(';')
        self.symExMap = dict(zip(self.symbolList, self.exchangeList))

        self.get_contract_info()
        self.manage_position()
        self.get_dynamic_rights()

        if str(self.period).isdigit():
            self.loadDay(years=1, func=self.on_bar_day)
            self.loadBar(days=1, func=self.on_bar)

        self.subSymbol()
        self.output(f'{self.name} 策略启动')

    def onTrade(self, trade: TradeData, log: bool = False) -> None:
        super().onTrade(trade, log)
        self.get_dynamic_rights()
        self.get_unit()  # 重新计算 unit

    def onTick(self, tick: TickData) -> None:
        if not tick.date:
            tick.date = tick.datetime.strftime('%Y%m%d')
        super().onTick(tick)

        if tick.lastPrice == 0:
            return

        self.tick = tick
        self.tick_price = tick.lastPrice
        self.putEvent()

        self.trading = True
        self.bm.updateTick(tick)

    def on_bar(self, bar):
        """收到Bar推送"""
        self.bm.updateBar(bar)

        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

    def on_xmin_bar(self, bar):
        """收到合成后的Bar推送"""

        if not self.am.updateBar(bar):
            return

        self.exec_signal()

    def on_bar_day(self, bar: KLineData) -> None:
        if self.tradeDate != bar.date:
            self.tradeDate = bar.date

        if not self.am_day.updateBar(bar):
            return

        self.get_unit()

    def get_contract_info(self) -> None:
        """获取并设置合约乘数"""
        contract_info = self.get_contract(self.exchange, self.vtSymbol)
        self.multiple = contract_info.size
        self.max_limit_order_volume = contract_info.max_limit_order_volume
        self.min_limit_order_volume = contract_info.min_limit_order_volume
        self.price_tick = contract_info.priceTick
        self.putEvent()

    def get_unit(self) -> None:
        self.up20, self.down20 = self.am_day.donchian(20)
        self.up10, self.down10 = self.am_day.donchian(10)
        self.atr, self.tr = self.am_day.atr(20)

        unit = min(int((0.01 * self.total_net) / (self.atr * self.multiple)), self.max_limit_order_volume)
        self.unit = max(unit, self.min_limit_order_volume)  # 无需取整，大于最小报单数后，下单会自动取整

        self.putEvent()

    def get_dynamic_rights(self) -> None:
        """获取并设置动态权益"""
        account_info: dict = ctaEngine.getInvestorAccount(self.get_investor())
        self.total_net: float = account_info.get("DynamicRights", 0.0)
        self.putEvent()
