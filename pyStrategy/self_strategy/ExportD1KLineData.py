# -*- coding: utf-8 -*-
r"""
InfiniTrader 日线K线批量导出策略

功能：导出与日线回测相同的 31 个品种的 D1（日线）K线数据
用途：供布林带做空策略进行正确周期的回测

使用方法：
1. 在 InfiniTrader 中加载此策略
2. 运行策略，将自动导出所有配置的合约
3. 数据保存到桌面 quanda_exports_d1/ 目录
"""

import json
import os
from datetime import datetime

from pythongo.ui import BaseStrategy
from pythongo.core import MarketCenter


class ExportD1KLineData(BaseStrategy):
    """日线K线批量导出策略"""

    def __init__(self) -> None:
        super().__init__()

        # 配置要导出的合约列表（当前活跃主力合约，2026-04-28 更新）
        self.contracts = [
            # 股指期货 - 中金所 (CFFEX)
            ("CFFEX", "IC2606", "中证500股指期货"),
            ("CFFEX", "IF2606", "沪深300股指期货"),
            ("CFFEX", "IH2606", "上证50股指期货"),
            ("CFFEX", "IM2606", "中证1000股指期货"),

            # 国债期货 - 中金所 (CFFEX)
            ("CFFEX", "T2609", "10年期国债期货"),
            ("CFFEX", "TF2609", "5年期国债期货"),
            ("CFFEX", "TS2609", "2年期国债期货"),

            # 商品期货 - 上期所 (SHFE)
            ("SHFE", "rb2610", "螺纹钢"),
            ("SHFE", "hc2610", "热卷"),
            ("SHFE", "cu2606", "铜"),
            ("SHFE", "al2606", "铝"),
            ("SHFE", "zn2606", "锌"),
            ("SHFE", "ni2606", "镍"),
            ("SHFE", "au2608", "黄金"),
            ("SHFE", "ag2606", "白银"),
            ("SHFE", "bu2606", "沥青"),
            ("SHFE", "ru2609", "橡胶"),

            # 商品期货 - 大商所 (DCE)
            ("DCE", "i2609", "铁矿石"),
            ("DCE", "m2609", "豆粕"),
            ("DCE", "y2609", "豆油"),
            ("DCE", "p2609", "棕榈油"),
            ("DCE", "a2609", "豆一"),
            ("DCE", "c2609", "玉米"),
            ("DCE", "cs2609", "玉米淀粉"),

            # 商品期货 - 郑商所 (CZCE)
            ("CZCE", "SR2609", "白糖"),
            ("CZCE", "CF2609", "棉花"),
            ("CZCE", "RM2609", "菜粕"),
            ("CZCE", "MA2609", "甲醇"),
            ("CZCE", "TA2609", "PTA"),
            ("CZCE", "FG2609", "玻璃"),
            ("CZCE", "SA2609", "纯碱"),
        ]

        self.export_dir = ""
        self.export_count = 0
        self.export_total = 0
        self.failed = []

    def on_init(self) -> None:
        """策略初始化"""
        from pythongo.infini import write_log

        write_log("=" * 60)
        write_log("日线K线批量导出策略")
        write_log("=" * 60)
        write_log(f"共配置 {len(self.contracts)} 个合约")

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.export_dir = os.path.join(desktop, "quanda_exports_d1")
        os.makedirs(self.export_dir, exist_ok=True)

        write_log(f"导出目录: {self.export_dir}")

    def on_start(self) -> None:
        """策略启动"""
        from pythongo.infini import write_log

        write_log("开始批量导出 D1 K线数据...")

        market_center = MarketCenter()
        self.export_total = 0

        for exchange, instrument, name in self.contracts:
            write_log(f"\n正在导出: {instrument} ({name}) - D1")

            try:
                kline_data = market_center.get_kline_data(
                    exchange=exchange,
                    instrument_id=instrument,
                    style="D1",
                    count=-10000
                )

                if not kline_data:
                    write_log(f"  无数据，跳过")
                    self.failed.append((instrument, "无数据"))
                    continue

                write_log(f"  获取到 {len(kline_data)} 条数据")

                export_data = []
                for bar in kline_data:
                    export_data.append({
                        "date": str(bar.get('datetime', ''))[:16] if bar.get('datetime') else '',
                        "code": instrument,
                        "open": float(bar.get('open', 0)),
                        "high": float(bar.get('high', 0)),
                        "low": float(bar.get('low', 0)),
                        "close": float(bar.get('close', 0)),
                        "volume": int(bar.get('volume', 0)),
                        "open_interest": int(bar.get('open_interest', 0)) if bar.get('open_interest') else 0,
                    })

                file_name = f"{instrument}_kline.json"
                file_path = os.path.join(self.export_dir, file_name)

                output = {
                    "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "exchange": exchange,
                    "instrument": instrument,
                    "name": name,
                    "kline_style": "D1",
                    "total_records": len(export_data),
                    "data": export_data
                }

                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)

                self.export_total += len(export_data)
                self.export_count += 1

                write_log(f"  已保存: {file_name} ({len(export_data)} 条)")

                if export_data:
                    write_log(f"  范围: {export_data[0]['date']} ~ {export_data[-1]['date']}")

            except Exception as e:
                write_log(f"  导出失败: {e}")
                self.failed.append((instrument, str(e)))

        super().on_start()

    def on_stop(self) -> None:
        """策略停止"""
        from pythongo.infini import write_log

        write_log("\n" + "=" * 60)
        write_log("D1 K线批量导出完成！")
        write_log(f"成功导出: {self.export_count}/{len(self.contracts)} 个合约")
        write_log(f"总记录数: {self.export_total}")
        write_log(f"导出目录: {self.export_dir}")

        if self.failed:
            write_log(f"\n失败的合约 ({len(self.failed)}):")
            for inst, reason in self.failed:
                write_log(f"  {inst}: {reason}")

        write_log("=" * 60)

        super().on_stop()
