"""
分钟级 K 线
last update: 2023年8月20日 17:36:47
"""

from ctaTemplate import CtaTemplate, KLWidget, TickData, KLineData
from utils import MinKLineGenerator


class Demo_MinLV_KLine(CtaTemplate):
    """分钟级 K 线图示例"""
    def __init__(self):
        super().__init__()
        self.paramMap = {
            'exchange': '交易所',
            'vtSymbol': '合约',
            'kline_style': 'K线类型'
        }

        self.varMap = {
            'trading': '交易中'
        }

        self.widgetClass = KLWidget
        self.widget: KLWidget = None
        self.kline_generator: MinKLineGenerator = None

        self.exchange = ''
        self.vtSymbol = ''
        self.kline_style = "M1" # K 线类型, 具体看 core.pyi 中的 KLineStyle 定义

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
        """这里默认合成 M1 的 K 线, 即 1 分钟 K 线, 具体可使用的合成分钟, 请看 KLineStyle 枚举类"""

        self.kline_generator = MinKLineGenerator(
            callback=self.on_min_kline,
            exchange=self.exchange,
            instrument=self.vtSymbol,
            style=self.kline_style
        )
        
        super().onStart()

    def on_min_kline(self, kline: KLineData) -> None:
        """推送 K 线回调
        当新的分钟线合成后, 会调用本函数, 这是因为在 onStart 中指定了本函数
        由于运行之前的 tick 数据获取不到, 所以第一根 K 线数据一般是错误的, 后面会改进
        你可以把计算信号的方法写在这
        在此示例中, 由于不使用 signal, 所以该值默认为 0
        """
        self.widget and self.widget.recv_kline({
            'bar': kline,
            'sig': self.signal
        })

    def onStop(self) -> None:
        if self.kline_generator:
            self.kline_generator.stop_push_scheduler()

        super().onStop()
