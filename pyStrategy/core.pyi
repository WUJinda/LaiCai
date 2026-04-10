from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal

__version__ = "1.23.08.21.a"


class KLineStyle(Enum):
    M1 = 1
    M2 = 2
    M3 = 3
    M4 = 4
    M5 = 5
    M10 = 10
    M15 = 15
    M30 = 30
    M45 = 45
    H1 = 60
    H2 = 120
    H3 = 180
    H4 = 240
    D1 = 1440

KLineStyleType = Literal[
    KLineStyle.M1,
    KLineStyle.M2,
    KLineStyle.M3,
    KLineStyle.M4,
    KLineStyle.M5,
    KLineStyle.M10,
    KLineStyle.M15,
    KLineStyle.M30,
    KLineStyle.M45,
    KLineStyle.H1,
    KLineStyle.H2,
    KLineStyle.H3,
    KLineStyle.H4,
    KLineStyle.D1
]


class MarketCenter(object):
    def __init__(self) -> None:    
        self.cache_trade_time: Dict[str, Dict] = {}
        self.cache_trade_section: Dict[str, Dict[str, str]] = {}

    def get_avl_close_time(self, instrument: str) -> List[datetime]:
        """从交易节中获取可使用的收盘时间序列"""
        ...

    def get_close_time(self, instrument: str) -> List[str]:
        """从交易节中获取收盘时间序列"""
        ...

    def get_kline_data(
        self,
        exchange: str,
        instrument: str,
        count: int,
        origin: int = None,
        style: KLineStyleType = KLineStyle.M1,
        simply: bool = True
    ) -> List[dict]:
        """获取 K 线数据

        Args:
            exchange: 交易所代码
            instrument: 合约代码
            count: 查询 K 线数量, 正值获取 origin 时间后的数量, 负值为之前
            origin: 基准时间戳
            style: K 线风格, 使用 KLineStyle 枚举值
            simply: 极简 K 线, 只返回带有 OHLC 和时间的 K 线
        """
        ...

    def get_kline_snapshot(self, exchange: str, instrument: str) -> dict:
        """获取 K 线快照"""
        ...

    def get_dominant_list(self, exchange: str) -> List[str]:
        """获取主连合约列表"""

    def get_instrument_trade_time(self, exchange: str, instrument: str, instant: int = None) -> dict:
        """查询合约带交易日的交易时段"""
        ...

    def get_product_trade_time(self, exchange: str, product: str, trading_day: str = None) -> dict:
        """查询品种的交易时段信息"""
        ...

    def get_next_gen_time(self, exchange: str, instrument: str, tick_time: datetime, style: KLineStyleType) -> datetime:
        """获取下一根 K 线生成时间"""
        ...
