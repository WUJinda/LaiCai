# -*- coding: utf-8 -*-
r"""
InfiniTrader 批量K线数据导出策略

功能：一次性导出多个合约的K线数据

使用方法：
1. 在 InfiniTrader 中加载此策略
2. 运行策略，将自动导出所有配置的合约
3. 数据保存到桌面，每个合约一个文件
"""

import json
import os
from datetime import datetime

from pythongo.base import BaseParams
from pythongo.ui import BaseStrategy
from pythongo.core import MarketCenter


class BatchExportKLineData(BaseStrategy):
    """批量K线数据导出策略"""

    def __init__(self) -> None:
        super().__init__()

        # 配置要导出的合约列表
        self.contracts = [
            # 股指期货 - 中金所 (CFFEX)
            ("CFFEX", "IC2603", "中证500股指期货"),
            ("CFFEX", "IF2603", "沪深300股指期货"),
            ("CFFEX", "IH2603", "上证50股指期货"),
            ("CFFEX", "IM2603", "中证1000股指期货"),

            # 国债期货 - 中金所 (CFFEX)
            ("CFFEX", "T2506", "10年期国债期货"),
            ("CFFEX", "TF2506", "5年期国债期货"),
            ("CFFEX", "TS2506", "2年期国债期货"),

            # 商品期货 - 上期所 (SHFE)
            ("SHFE", "rb2601", "螺纹钢"),
            ("SHFE", "hc2506", "热卷"),
            ("SHFE", "cu2506", "铜"),
            ("SHFE", "al2506", "铝"),
            ("SHFE", "zn2506", "锌"),
            ("SHFE", "ni2506", "镍"),
            ("SHFE", "au2506", "黄金"),
            ("SHFE", "ag2606", "白银"),
            ("SHFE", "bu2506", "沥青"),
            ("SHFE", "ru2506", "橡胶"),

            # 商品期货 - 大商所 (DCE)
            ("DCE", "i2505", "铁矿石"),
            ("DCE", "m2505", "豆粕"),
            ("DCE", "y2505", "豆油"),
            ("DCE", "p2505", "棕榈油"),
            ("DCE", "a2505", "豆一"),
            ("DCE", "c2505", "玉米"),
            ("DCE", "cs2505", "玉米淀粉"),

            # 商品期货 - 郑商所 (CZCE)
            ("CZCE", "SR2505", "白糖"),
            ("CZCE", "CF2505", "棉花"),
            ("CZCE", "RM2505", "菜粕"),
            ("CZCE", "MA2505", "甲醇"),
            ("CZCE", "TA2505", "PTA"),
            ("CZCE", "FG2505", "玻璃"),
            ("CZCE", "SA2505", "纯碱"),
        ]

        self.export_dir = ""
        self.export_count = 0
        self.export_total = 0

    def on_init(self) -> None:
        """策略初始化"""
        from pythongo.infini import write_log

        write_log("=" * 60)
        write_log("批量K线数据导出策略")
        write_log("=" * 60)
        write_log(f"共配置 {len(self.contracts)} 个合约")

        # 设置导出目录
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.export_dir = os.path.join(desktop, "quanda_exports")
        os.makedirs(self.export_dir, exist_ok=True)

        write_log(f"导出目录: {self.export_dir}")

    def on_start(self) -> None:
        """策略启动"""
        from pythongo.infini import write_log

        write_log("开始批量导出...")

        market_center = MarketCenter()
        self.export_total = 0

        for exchange, instrument, name in self.contracts:
            write_log(f"\n正在导出: {instrument} ({name})")

            try:
                # 获取历史K线数据
                kline_data = market_center.get_kline_data(
                    exchange=exchange,
                    instrument_id=instrument,
                    style="D1",
                    count=-10000
                )

                if not kline_data:
                    write_log(f"  无数据，跳过")
                    continue

                write_log(f"  获取到 {len(kline_data)} 条数据")

                # 转换数据格式
                export_data = []
                for bar in kline_data:
                    export_data.append({
                        "date": str(bar.get('datetime', ''))[:10] if bar.get('datetime') else '',
                        "code": instrument,
                        "open": float(bar.get('open', 0)),
                        "high": float(bar.get('high', 0)),
                        "low": float(bar.get('low', 0)),
                        "close": float(bar.get('close', 0)),
                        "volume": int(bar.get('volume', 0)),
                        "open_interest": int(bar.get('open_interest', 0)) if bar.get('open_interest') else 0,
                    })

                # 保存到文件
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

                write_log(f"  已保存: {file_name}")

                # 显示数据范围
                if export_data:
                    write_log(f"  范围: {export_data[0]['date']} 到 {export_data[-1]['date']}")

            except Exception as e:
                write_log(f"  导出失败: {e}")

        super().on_start()

    def on_stop(self) -> None:
        """策略停止"""
        from pythongo.infini import write_log

        write_log("\n" + "=" * 60)
        write_log("批量导出完成！")
        write_log(f"成功导出: {self.export_count} 个合约")
        write_log(f"总记录数: {self.export_total}")
        write_log(f"导出目录: {self.export_dir}")
        write_log("=" * 60)

        super().on_stop()
