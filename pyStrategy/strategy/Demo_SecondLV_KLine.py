"""
秒级 K 线
last update: 2023年10月13日 11:34:49
"""

from ctaTemplate import CtaTemplate, KLWidget, KLineData, TickData
from utils import KLineGenerator


class Demo_SecondLV_KLine(CtaTemplate):
    """秒级 K 线图示例"""
    def __init__(self):
        super().__init__()
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '合约',
            'seconds': '秒数'
        }

        self.varMap = {
            'trading': '交易中'
        }

        self.widgetClass = KLWidget
        self.widget: KLWidget = None
        self.kline_generator: KLineGenerator = None

        self.exchange = ''
        self.vtSymbol = ''
        self.seconds = 5

        self.signal = 0
        self.mainSigs = []
        self.subSigs = []


    def onInit(self):
        super().onInit()
        self.getGui()

    def onTick(self, tick: TickData) -> None:
        super().onTick(tick)
        self.kline_generator.tick_to_kline(tick)

    def onStart(self) -> None:
        self.kline_generator = KLineGenerator(
            callback=self.on_secend_kline,
            seconds=self.seconds
        )

        #: 由于秒级 K 线没有历史数据，所以需要在这里手动设置线图横坐标变化事件
        self.widget.set_xrange_event_signal.emit()

        super().onStart()

    def on_secend_kline(self, kline: KLineData) -> None:
        """推送 K 线回调, 由于不使用 signal, 所以该值默认为 0"""
        self.widget.recv_kline({
            'bar': kline,
            'sig': self.signal
        })
