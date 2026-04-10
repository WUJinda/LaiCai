# -*- coding: utf-8 -*-
r"""
InfiniTrader K线数据导出策略

功能：从 InfiniTrader 获取指定合约的K线数据并导出到 JSON 文件

使用方法：
1. 在 InfiniTrader 中加载此策略
2. 设置参数（交易所代码、合约代码等）
3. 运行策略，数据将保存到桌面的 quanda_kline_export.json 文件
4. 运行 python bin/import_exported_kline.py 导入到 MongoDB
"""

import json
import os
from datetime import datetime
from typing import Literal

from pythongo.base import BaseParams, Field
from pythongo.classdef import KLineData, TickData
from pythongo.core import KLineStyle
from pythongo.ui import BaseStrategy
from pythongo.utils import KLineGenerator


class Params(BaseParams):
    """参数映射模型"""
    exchange: str = Field(default="SHFE", title="交易所代码(SHFE/CFFEX/DCE/CZCE)")
    instrument_id: str = Field(default="rb2505", title="合约代码")
    kline_style: KLineStyle = Field(default="D1", title="K线周期(D1日线/M1分钟)")


class ExportKLineData(BaseStrategy):
    """K线数据导出策略"""

    def __init__(self) -> None:
        super().__init__()

        self.params_map = Params()
        """参数表"""

        self.kline_generator: KLineGenerator = None
        """K线合成器"""

        self.export_data: list[dict] = []
        """导出的数据列表"""

        self.export_file: str = ""
        """导出文件路径"""

    def on_init(self) -> None:
        """策略初始化"""
        from pythongo.infini import write_log

        write_log("=" * 50)
        write_log("K线数据导出策略")
        write_log("=" * 50)
        write_log(f"交易所: {self.params_map.exchange}")
        write_log(f"合约: {self.params_map.instrument_id}")
        write_log(f"周期: {self.params_map.kline_style}")

        # 设置导出文件路径
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.export_file = os.path.join(desktop, "quanda_kline_export.json")

        write_log(f"导出文件: {self.export_file}")

    def on_tick(self, tick: TickData) -> None:
        """收到行情 tick 推送"""
        super().on_tick(tick)

        if self.kline_generator:
            self.kline_generator.tick_to_kline(tick)

    def on_start(self) -> None:
        """策略启动"""
        from pythongo.infini import write_log
        from pythongo.core import MarketCenter

        write_log("开始获取历史数据...")

        # 直接使用 MarketCenter 获取更多历史数据
        market_center = MarketCenter()

        # 获取历史K线数据，count=-10000 表示获取之前10000条数据
        kline_data = market_center.get_kline_data(
            exchange=self.params_map.exchange,
            instrument_id=self.params_map.instrument_id,
            style=self.params_map.kline_style,
            count=-10000  # 获取之前10000条数据
        )

        write_log(f"从 MarketCenter 获取到 {len(kline_data)} 条原始数据")

        # 转换并添加到导出列表
        for bar in kline_data:
            data = {
                "date": str(bar.get('datetime', ''))[:10] if bar.get('datetime') else '',
                "code": self.params_map.instrument_id,
                "open": float(bar.get('open', 0)),
                "high": float(bar.get('high', 0)),
                "low": float(bar.get('low', 0)),
                "close": float(bar.get('close', 0)),
                "volume": int(bar.get('volume', 0)),
                "open_interest": int(bar.get('open_interest', 0)) if bar.get('open_interest') else 0,
            }
            self.export_data.append(data)

        write_log(f"历史数据获取完成，共 {len(self.export_data)} 条")

        super().on_start()

    def on_stop(self) -> None:
        """策略停止"""
        from pythongo.infini import write_log

        # 导出数据到文件
        self.export_to_file()

        write_log("=" * 50)
        write_log("数据导出完成！")
        write_log(f"文件: {self.export_file}")
        write_log(f"记录数: {len(self.export_data)}")
        write_log("=" * 50)

        super().on_stop()

    def callback(self, kline: KLineData) -> None:
        """接收K线数据回调"""
        from pythongo.infini import write_log

        # 转换为字典格式
        data = {
            "date": kline.datetime.strftime("%Y-%m-%d") if hasattr(kline.datetime, 'strftime') else str(kline.datetime),
            "code": self.params_map.instrument_id,
            "open": float(kline.open),
            "high": float(kline.high),
            "low": float(kline.low),
            "close": float(kline.close),
            "volume": int(kline.volume),
            "open_interest": int(kline.open_interest) if kline.open_interest else 0,
        }

        self.export_data.append(data)

        # 每50条输出一次日志
        if len(self.export_data) % 50 == 0:
            write_log(f"已收集 {len(self.export_data)} 条数据...")

        # 不再发送到界面，避免 widget 错误

    def export_to_file(self) -> None:
        """导出数据到JSON文件"""
        if not self.export_data:
            return

        export_data = {
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exchange": self.params_map.exchange,
            "instrument": self.params_map.instrument_id,
            "kline_style": str(self.params_map.kline_style),
            "total_records": len(self.export_data),
            "data": self.export_data
        }

        try:
            with open(self.export_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            from pythongo.infini import write_log
            write_log(f"导出文件失败: {e}")
