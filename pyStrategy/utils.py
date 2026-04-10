import threading
from datetime import datetime, timedelta
from typing import Any, Callable, List, Literal, Union

import numpy as np
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler

from core import KLineStyle, KLineStyleType, MarketCenter
from indicators import Indicators
from vtObject import KLineData, TickData

DateTimeType = datetime


class Scheduler(object):
    """简易定时器"""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()

    def add_job(self, func: Any, trigger: Literal['date', 'interval', 'cron'], **kwargs) -> None:
        """添加定时任务"""
        self.scheduler.add_job(func=func, trigger=trigger, **kwargs)

    def get_job(self, job_id: str, jobstore: str = None) -> Job:
        """根据 job_id 获取对应的定时任务"""
        return self.scheduler.get_job(job_id=job_id, jobstore=jobstore)

    def get_jobs(self, jobstore: str = None) -> List[Job]:
        """返回所有的定时任务"""
        return self.scheduler.get_jobs(jobstore)

    def start(self) -> None:
        """启动定时器"""
        if self.scheduler.running is False:
            self.scheduler.start()

    def stop(self) -> None:
        """停止定时器"""
        if self.scheduler.running:
            self.scheduler.shutdown()


class KLineGenerator(object):
    """秒级 K 线生成器

    Args:
        callback: 推送 K 线回调, 也可以是任何接受一根 K 线然后返回 None 的函数\n
        seconds: 合成秒数
    """

    def __init__(self, callback: Callable[[KLineData], None], seconds: int = 1) -> None:
        self.callback = callback
        self.seconds = seconds

        self.cache_kline: KLineData = None
        self.last_tick: TickData = None
        self.is_new: bool = True
        self.timekeeper: List[datetime] = []

    @property
    def seconds(self) -> int:
        return self._seconds

    @seconds.setter
    def seconds(self, value: int) -> None:
        if not isinstance(value, int):
            raise ValueError("秒数必须为 int 类型")
        self._seconds: int = value

    @property
    def first_time(self) -> datetime:
        """获取第一条 tick 的时间"""
        return self.timekeeper[0]

    @property
    def last_k_time(self) -> datetime:
        """获取上一条 K 线的时间"""
        return self.sort_timekeeper[self.seconds - 1]

    @property
    def sort_timekeeper(self) -> List[datetime]:
        """对时间线去重"""
        return sorted(set(self.timekeeper), key=self.timekeeper.index)

    @staticmethod
    def _ts(_datetime: datetime) -> int:
        """获取 datetime 对象的时间戳"""
        return int(_datetime.timestamp())

    def save_time(self, _time: datetime) -> None:
        """对时间去除毫秒数并保存至时间线"""
        self.timekeeper.append(_time.replace(microsecond=0))

    def fix_timeline(self, tick: TickData) -> None:
        """修复时间线中缺失的时间"""
        lost_seconds: int = self._ts(tick.datetime) - self._ts(self.last_tick.datetime)
        if (lost_ticks := (lost_seconds - 1)) > 0:
            # 如果少了 tick，则手动补全 timekeeper
            for j in range(lost_ticks, 0, -1):
                self.timekeeper.insert(-1, (tick.datetime - timedelta(seconds=j)).replace(microsecond=0))

    def set_kline_data(self, **kwargs) -> None:
        """对当前缓存的 K 线设置数据"""
        self.cache_kline.__dict__.update(kwargs)

    def new_kline_cycle(self, tick: TickData) -> bool:
        """判断该 tick 是否进入新的 K 线周期"""
        if not self.cache_kline:
            # 首次运行
            return False

        diff_seconds: int = self._ts(tick.datetime) - self._ts(self.first_time)

        self.fix_timeline(tick)

        if diff_seconds >= self.seconds:
            # 新 tick 时间和时间容器中第一根 tick 时间秒数对比
            # 如果大于等于设置的秒数，则表示进入新的 K 线周期
            # 然后要修复时间线，在把时间线中正确的时间赋予当前缓存 K 线
            # 最后把该 K 线时间之后的时间重新赋值给时间线，成为新的时间线

            self.set_kline_data(
                date=self.last_k_time.strftime("%Y%m%d"),
                time=self.last_k_time.strftime("%X"),
                datetime=self.last_k_time
            )
            self.timekeeper = self.sort_timekeeper[self.seconds:]

            return True

    def tick_to_kline(self, tick: TickData) -> None:
        if self.is_new and tick.datetime.microsecond >= 500000:
            # 第一次运行，要毫秒数要小于 500ms，并且 self.seconds 能被 tick 的秒数整除
            return

        self.save_time(tick.datetime)

        if self.new_kline_cycle(tick):
            self.is_new = True
            self.callback(self.cache_kline)

        if self.is_new:
            self.is_new = False
            self.cache_kline = KLineData()

            self.set_kline_data(
                vtSymbol=tick.symbol,
                symbol=tick.symbol,
                exchange=tick.exchange,
                open=tick.lastPrice,
                close=tick.lastPrice,
                high=tick.lastPrice,
                low=tick.lastPrice,
                date=tick.date,
                time=tick.time,
                datetime=tick.datetime,
                openInterest=tick.openInterest
            )
        else:
            self.set_kline_data(
                close=tick.lastPrice,
                high=max(self.cache_kline.high, tick.lastPrice),
                low=min(self.cache_kline.low, tick.lastPrice),
                volume=self.cache_kline.volume + (tick.volume - self.last_tick.volume)
            )

        self.last_tick = tick


class MinKLineGenerator(object):
    """分钟级 K 线合成
    ----
    Args:
        callback: 推送 K 线回调, 也可以是任何接受一根 K 线然后返回 None 的函数\n
        exchange: 交易所代码\n
        instrument: 合约代码\n
        style: 合成 K 线分钟, 默认 M1 即 1 分钟 K 线, 必须使用 KLineStyle 的枚举值\n
        real_time_callback: 实时推送 K 线回调, 推送频率和 tick 相同
    """

    def __init__(
        self,
        callback: Callable[[KLineData], None],
        exchange: str,
        instrument: str,
        style: Union[KLineStyleType, str] = KLineStyle.M1,
        real_time_callback: Callable[[KLineData], None] = None
    ) -> None:
        self.callback = callback
        self.exchange = exchange
        self.instrument = instrument
        self.style = style
        self.real_time_callback = real_time_callback

        self.scheduler = Scheduler()
        self.market_center = MarketCenter()
        self.producer = KLineProducer(
            exchange=self.exchange,
            instrument=self.instrument,
            style=style,
            callback=callback
        )

        self.next_gen_time: datetime = None

        self._first_run: bool = True
        self._is_new: bool = True
        self._cache_kline: KLineData = None
        self._last_tick: TickData = None
        self._min_last_tick: TickData = None
        self._min_last_volume: int = 0
        self._dirty_time: datetime = None

    @property
    def style(self) -> KLineStyleType:
        return self._style

    @style.setter
    def style(self, value: Union[KLineStyleType, str]) -> None:
        if value in KLineStyle.__members__:
            self._style: KLineStyleType = KLineStyle[value]
        elif isinstance(value, KLineStyle):
            self._style: KLineStyleType = value
        else:
            raise ValueError("合成分钟必须为 KLineStyle 的枚举值")

    def stop_push_scheduler(self) -> None:
        """停止定时器"""
        self.scheduler.stop()

    def _set_kline_data(self, **kwargs) -> None:
        """对当前缓存的 K 线设置数据"""
        self._cache_kline.__dict__.update(kwargs)

    def _ts_to_datetime(self, ts: int, full_date: bool = False) -> datetime:
        """
        毫秒时间戳转时间类型, 默认去除秒和毫秒

        Args:
            ts: 毫秒时间戳\n
            full_date: 是否返回完整时间
        """
        _datetime = datetime.fromtimestamp(ts / 1000)
        if full_date:
            return _datetime
        return _datetime.replace(second=0, microsecond=0)

    def _init_kline(self, tick: TickData) -> None:
        """使用 K 线快照和第一个 tick 初始化第一根 K 线"""
        self._first_run = False
        self._cache_kline = KLineData()

        if not (snapshot := self.get_kline_snapshot()):
            return

        head_ts: int = snapshot["timestampHead"]
        tail_ts: int = snapshot["timestampTail"]
        tick_ts: int = int(tick.datetime.timestamp() * 1000)

        head_time = self._ts_to_datetime(head_ts)
        tail_time = self._ts_to_datetime(tail_ts)
        tick_time = tick.datetime.replace(second=0, microsecond=0)

        if head_ts == tail_ts or tick.date != tail_time.strftime("%Y%m%d"):
            """tick 和快照交易日不同"""
            return

        self._is_new = False

        self._set_kline_data(
            exchange=tick.exchange,
            symbol=tick.symbol,
            open=snapshot["openPrice"],
            high=snapshot["highestPrice"],
            low=snapshot["lowestPrice"],
            close=snapshot["closePrice"],
            volume=snapshot["volume"],
            openInterest=snapshot["openInterest"],
            datetime=self.next_gen_time
        )

        if head_time == tick_time:
            """tick 和快照在同一交易分钟"""
            self._min_last_volume = snapshot["totalVolume"] - snapshot["volume"]

            if (
                tick_ts < head_ts
                or head_ts < tick_ts < tail_ts
                or tick_ts == tail_ts
            ):
                """
                tick 在快照之前
                tick 在快照中间
                tick 是快照的最后一个 tick
                """
                if tick_ts < head_ts:
                    self._set_kline_data(
                        open=tick.lastPrice,
                        high=max(self._cache_kline.high, tick.lastPrice),
                        low=min(self._cache_kline.low, tick.lastPrice)
                    )

                self._dirty_time = self._ts_to_datetime(tail_ts, full_date=True)
            elif tick_ts > tail_ts:
                """tick 在快照之后"""
                self._set_kline_data(
                    high=max(self._cache_kline.high, tick.lastPrice),
                    low=min(self._cache_kline.low, tick.lastPrice),
                    close=tick.lastPrice,
                    volume=tick.volume - self._min_last_volume,
                    openInterest=tick.openInterest
                )
        elif tick_time < head_time:
            """tick 在快照之前, 不在同一交易分钟"""
            self._dirty_time = self._ts_to_datetime(tail_ts, full_date=True)
        elif tail_time < tick_time:
            """tick 在快照之后，不在同一交易分钟, 未对比 tick.volume 和 snap.volume"""
            self._set_kline_data(
                open=tick.lastPrice,
                high=tick.lastPrice,
                low=tick.lastPrice,
                close=tick.lastPrice,
                volume=0,
                openInterest=tick.openInterest
            )

        self._first_run = False

    def get_next_gen_time(self, tick_time: datetime) -> dict:
        """获取下一根 K 线合成时间"""
        self.next_gen_time = self.market_center.get_next_gen_time(
            exchange=self.exchange,
            instrument=self.instrument,
            tick_time=tick_time,
            style=self.style
        )

    def get_kline_snapshot(self) -> dict:
        """获取 K 线快照"""
        return self.market_center.get_kline_snapshot(
            exchange=self.exchange,
            instrument=self.instrument
        )

    def save_kline(self, data: List[dict]) -> None:
        """保存 K 线数据到 KLineContainer"""
        self.producer.kline_container.set(
            exchange=self.exchange,
            instrument=self.instrument,
            style=self.style,
            data=data
        )

    def _push_kline(self) -> None:
        """推送 K 线"""
        if self._lose_kline:
            """缺少 K 线，需要在第一次推送的时候补上"""
            self._lose_kline = None
            kline_data = self.market_center.get_kline_data(
                exchange=self.exchange,
                instrument=self.instrument,
                count=-365,
                style=self.style
            )

            for kline in kline_data:
                if kline["datetime"] in self.producer.datetime:
                    continue

                self.save_kline([kline])

                _kline = KLineData()
                _kline.__dict__.update(
                    exchange=self.exchange,
                    symbol=self.instrument,
                    **kline
                )

                self.producer.update(_kline)
                self.callback(_kline)

        self._set_kline_data(
            volume=self._last_tick.volume - self._min_last_volume,
            datetime=self.next_gen_time
        )

        self.save_kline([
            {
                'open': self._cache_kline.open,
                'close': self._cache_kline.close,
                'low': self._cache_kline.low,
                'high': self._cache_kline.high,
                'volume': self._cache_kline.volume,
                'datetime': self._cache_kline.datetime,
                'open_interest': self._cache_kline.openInterest
            }
        ])

        self.producer.update(self._cache_kline)
        self.callback(self._cache_kline)

        self._is_new = True
        self._min_last_tick = self._last_tick
        self._min_last_volume = self._last_tick.volume

    def tick_to_kline(self, tick: TickData, push: bool = False) -> None:
        """合成 K 线"""
        if push and self.next_gen_time == datetime.now().replace(second=0, microsecond=0):
            """定时推送, 以保证在收盘后能收到最后一根 K 线, 之后需要清空下一次的生成时间"""
            self._push_kline()
            self.next_gen_time = None
            return

        if (
            tick.symbol != self.instrument
            or not tick.volume
            or (
                self._last_tick
                and self._last_tick.volume == tick.volume
            )
        ):
            return

        if self._first_run:
            """首次开始合成, 用当前 tick 的成交量作为上一分钟最后一个 tick 的成交量"""
            self._min_last_volume = tick.volume

            if (tick.datetime.timestamp() - datetime.now().timestamp()) > 600:
                """tick 时间大于当前时间"""
                return

            self._lose_kline = tick.datetime.replace(
                second=0,
                microsecond=0
            ) != self.producer.datetime[-1]

            self.get_next_gen_time(tick.datetime)

            self._init_kline(tick)

            for run_date in self.market_center.get_avl_close_time(tick.symbol):
                """添加推送任务"""
                self.scheduler.add_job(
                    func=self.tick_to_kline,
                    trigger="date",
                    run_date=run_date + timedelta(seconds=2),
                    args=[None, True]
                )

            if self.scheduler.get_jobs():
                self.scheduler.start()

            self.close_time = self.market_center.get_close_time(tick.symbol)
            self._last_tick = tick

            return

        if self._dirty_time and tick.datetime < self._dirty_time:
            """脏数据"""
            return

        if not self.next_gen_time:
            """下一次生成时间为空, 说明上一个 tick 是在盘后收到的"""
            self.get_next_gen_time(tick.datetime)
            if not self.next_gen_time:
                return

        if tick.datetime.replace(microsecond=0) >= self.next_gen_time:
            """tick 时间大于等于下一次生成时间则开始合成 K 线"""
            if tick.datetime.strftime("%X") not in self.close_time:
                """每个交易时段结束后的两个 tick 不驱动 K 线合成"""
                self._push_kline()
                self.get_next_gen_time(tick.datetime)

        if self._is_new:
            """新 K 线开始"""
            self._is_new = False
            self._cache_kline = KLineData()

            self._set_kline_data(
                exchange=tick.exchange,
                symbol=tick.symbol,
                open=tick.lastPrice,
                high=tick.lastPrice,
                low=tick.lastPrice,
            )
        else:
            self._set_kline_data(
                high=max(self._cache_kline.high, tick.lastPrice),
                low=min(self._cache_kline.low, tick.lastPrice)
            )

        if self._min_last_tick and self._min_last_tick.volume < tick.volume:
            self._set_kline_data(open=tick.lastPrice)
            self._min_last_tick = None

        self._set_kline_data(
            close=tick.lastPrice,
            openInterest=tick.openInterest,
            volume=(
                tick.volume
                if (volume := tick.volume - self._min_last_volume) < 0
                else volume
            ),
            datetime=self.next_gen_time
        )

        if callable(self.real_time_callback) and self.next_gen_time:
            """实时推送合成数据"""
            self.producer.update(self._cache_kline)
            self.real_time_callback(self._cache_kline)

        self._last_tick = tick


class KLineContainer(object):
    """K 线容器
    ----
        可以自动缓存实例本身, 重复的交易所及合约不再重新获取 K 线

    Args:
        exchange: 交易所代码\n
        instrument: 合约代码
    """

    _lock_1 = threading.Lock()
    _lock_2 = threading.Lock()
    _instance = None
    __init_flag = False

    def __new__(cls, *args, **kwargs):
        with cls._lock_1:
            if cls._instance is None:
                """只需要在 new class 的时候初始化 all_kline"""
                cls._instance = super().__new__(cls)
                cls._instance.all_kline = {}
            return cls._instance

    def __init__(
        self,
        exchange: str,
        instrument: str,
        style: KLineStyleType,
    ) -> None:
        super().__init__()

        with self._lock_2:
            if self.__init_flag and self.get(exchange, instrument, style):
                return

        self.market_center = MarketCenter()

        self.init(exchange, instrument, style)

        self.__init_flag = True

    def get(self, exchange: str, instrument: str, style: KLineStyleType) -> List[dict]:
        """根据交易所, 合约和 K 线分钟获取 K 线"""
        if isinstance(style, KLineStyle):
            return self.all_kline.get(exchange, {}).get(instrument, {}).get(style.name, [])
        return []

    def set(
        self,
        exchange: str,
        instrument: str,
        style: KLineStyleType,
        data: List[dict]
    ) -> None:
        """根据交易所, 合约和 K 线分钟缓存 K 线"""
        if isinstance(style, KLineStyle):
            self.all_kline.setdefault(exchange, {}).setdefault(
                instrument, {}).setdefault(style.name, []).extend(data)

    def init(self, exchange: str, instrument: str, style: KLineStyleType) -> None:
        """获取合约 K 线并缓存"""
        if not all([exchange, instrument]):
            raise ValueError("交易所或合约代码为空")

        if not (data := self.market_center.get_kline_data(
            exchange=exchange,
            instrument=instrument,
            style=style.name,
            count=-1440
        )):
            raise ValueError(f"获取到空数据, 请检查交易所 {exchange} 或者合约代码 {instrument} 是否填写错误")

        self.set(
            exchange=exchange,
            instrument=instrument,
            style=style,
            data=data
        )


class KLineProducer(Indicators):
    """K 线生产器
    ----
        初始化获取 M1 分钟 K 线, 后续使用 M1 分钟 K 线合成 N 分钟 K 线\n
        内置指标
        
    Args:
        exchange: 交易所代码\n
        instrument: 合约代码\n
        style: 合成 K 线分钟\n
            默认 M1 即 1 分钟 K 线, 必须使用 KLineStyle 的枚举值\n
        callback: 推送 K 线回调
        """
    def __init__(
        self,
        exchange: str,
        instrument: str,
        style: Union[KLineStyleType, str] = "M1",
        callback: Callable[[KLineData], None] = None
    ) -> None:
        super().__init__()
        self.style = style
        self.exchange = exchange
        self.instrument = instrument
        self.callback = callback

        self.kline_container = KLineContainer(
            exchange=exchange,
            instrument=instrument,
            style=self.style
        )

        if callback and hasattr(callback, "__self__"):
            """直接把当前实例注入到回调函数的类中"""
            callback.__self__.indicators = self

        self._first_run = True
        self._cache_kline: KLineData = None

        self._open = np.zeros(10)
        self._close = np.zeros(10)
        self._high = np.zeros(10)
        self._low = np.zeros(10)
        self._volume = np.zeros(10)
        self._datetime = np.arange(
            '1999-11-20 00',
            '1999-11-20 10',
            dtype='datetime64[h]'
        )

        self.worker()

    @property
    def style(self) -> KLineStyleType:
        return self._style

    @style.setter
    def style(self, value: Union[KLineStyleType, str]) -> None:
        if value in KLineStyle.__members__:
            self._style: KLineStyleType = KLineStyle[value]
        elif isinstance(value, KLineStyle):
            self._style: KLineStyleType = value
        else:
            raise ValueError("合成分钟必须为 KLineStyle 的枚举值")

    def _get_data(self) -> List[dict]:
        """根据 K 线类型获取对应的 K 线"""
        return self.kline_container.get(self.exchange, self.instrument, self.style)

    @property
    def open(self) -> List[np.float64]:
        """开盘价序列"""
        return self._open

    @open.setter
    def open(self, value: List[np.float64]) -> None:
        self._open = value

    @property
    def close(self) -> List[np.float64]:
        """收盘价序列"""
        return self._close

    @close.setter
    def close(self, value: List[np.float64]) -> None:
        self._close = value

    @property
    def high(self) -> List[np.float64]:
        """最高价序列"""
        return self._high

    @high.setter
    def high(self, value: List[np.float64]) -> None:
        self._high = value

    @property
    def low(self) -> List[np.float64]:
        """最低价序列"""
        return self._low

    @low.setter
    def low(self, value: List[np.float64]) -> None:
        self._low = value

    @property
    def volume(self) -> List[np.float64]:
        """成交量序列"""
        return self._volume

    @volume.setter
    def volume(self, value: List[np.float64]) -> None:
        self._volume = value

    @property
    def datetime(self) -> List[DateTimeType]:
        """时间序列"""
        return self._datetime

    @datetime.setter
    def datetime(self, value: List[DateTimeType]) -> None:
        self._datetime = value

    def update(self, kline: KLineData) -> None:
        """
        更新数据序列
        
        Args:
            kline: K 线对象
        """
        if self.datetime[-2] < kline.datetime < self.datetime[-1]:
            self.insert_data(kline)
        elif self.datetime[-1] != kline.datetime:
            self.append_data(kline)
        else:
            self.update_last_kline(kline)

    def append_data(self, kline: KLineData) -> None:
        """添加 K 线数据"""
        self.open = np.append(self.open, kline.open)
        self.close = np.append(self.close, kline.close)
        self.high = np.append(self.high, kline.high)
        self.low = np.append(self.low, kline.low)
        self.volume = np.append(self.volume, kline.volume)
        self.datetime = np.append(self.datetime, kline.datetime)

    def insert_data(self, kline: KLineData, index: int = -1) -> None:
        """插入 K 线数据"""
        self.open = np.insert(self.open, index, kline.open, axis=0)
        self.close = np.insert(self.close, index, kline.close, axis=0)
        self.high = np.insert(self.high, index, kline.high, axis=0)
        self.low = np.insert(self.low, index, kline.low, axis=0)
        self.volume = np.insert(self.volume, index, kline.volume, axis=0)
        self.datetime = np.insert(self.datetime, index, kline.datetime, axis=0)

    def update_last_kline(self, kline: KLineData) -> None:
        """更新最后一根 K 线数据"""
        self.open[-1] = kline.open
        self.close[-1] = kline.close
        self.high[-1] = kline.high
        self.low[-1] = kline.low
        self.volume[-1] = kline.volume
        self.datetime[-1] = kline.datetime

    def _set_kline_data(self, **kwargs) -> None:
        """对当前缓存的 K 线设置数据"""
        self._cache_kline.__dict__.update(kwargs)

    def _get_next_gen_time(self, _datetime) -> None:
        """根据传入的时间与 K 线时间类型生成下一根 K 线的开始时间"""
        self.next_gen_time = self.kline_container.market_center.get_next_gen_time(
            exchange=self.exchange,
            instrument=self.instrument,
            tick_time=_datetime,
            style=self.style
        )

    def _push(self) -> None:
        self.update(self._cache_kline)

        if callable(self.callback):
            """如果回调可用, 则使用回调"""
            self.callback(self._cache_kline)

    def worker(self) -> None:
        """将 K 线数据转成 K 线对象后推送"""
        if not (data := self._get_data()):
            return

        for kline in data:
            if not kline.get("open"):
                """空 K 线, Padding"""
                continue

            self._cache_kline = KLineData()

            self._set_kline_data(
                exchange=self.exchange,
                symbol=self.instrument,
                **kline,
                openInterest=kline["open_interest"],
            )

            self._push()


def isdigit(value: str) -> bool:
    """判断字符串是否小数"""
    value: str = value.lstrip('-')

    if value.isdigit():
        return True

    if (
        value.count(".") == 1
        and not value.startswith(".")
        and not value.endswith(".")
        and value.replace(".", "").isdigit()
    ):
        return True

    return False

def deprecated(new_func_name: str, log_func: Callable[[str], None]) -> Callable:
    """函数弃用提示装饰器"""
    def decorator(func: Callable[[], Any]) -> Callable:
        def wrap_func(*args, **kwargs) -> Any:
            log_func(f"[函数弃用提示] {func.__name__} 方法即将在后续版本弃用, " +
                f"请尽快改用新方法: {new_func_name}, 具体使用方法请看官网文档说明")
            return func(*args, **kwargs)
        return wrap_func
    return decorator
