import traceback
from typing import List

from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from ctaBase import *
from ctaTemplate import CtaTemplate
from vtObject import TickData

ORDER_CLOSE = 1
ORDER_CLOSETODAY = 2
ORDER_LONG = 0

class Demo_sendOrder(CtaTemplate):
    """仅供测试_两键下单"""
    def __init__(self):
        super().__init__()
        # 参数映射表
        self.paramMap = {
            'investor': '投资者帐号'
        }

        # 变量映射表
        self.varMap = {
            'trading': '交易中',
            'pos': '仓位'
        }

        self.vtSymbol = ''
        self.exchange = ''

        self.P = 0  # 买入触发价
        self.V = 0  # 下单手数
        self.widgetClass = TradingWidget1
        self.widget: TradingWidget1 = None
        self.orderDir = ORDER_LONG  # 报单方向
        self.mmPrice = self.P  # 报单价
        self.pSpread = 0
        self.he = '否'
        self.excSymbol = ''  # 交易合约
        self.excexchange = ''  # 对冲合约
        self.tickers = {}  # 所有切片
        self.upPrice = {}  # 涨停价
        self.lowPrice = {}  # 跌停价
        self.askPrice1 = {}  # 卖盘价1
        self.bidPrice1 = {}  # 买盘价1
        self.midPrice = {}  # 盘口中价
        self.askVolume1 = {}  # 卖盘量1
        self.bidVolume1 = {}  # 买盘量1
        self.mPrice = 1
        self.openOrderInfo = {}  # 开仓委托信息
        self.closeOrderInfo = {}  # 平仓委托信息
        self.posL = 0  # 多头持仓
        self.posS = 0  # 空头持仓
        self.poshL = 0  # 对冲多头持仓
        self.poshS = 0  # 对冲空头持仓
        self.lastvolume = {}
        self.a = 0
        self.sig = 0
        self.buyid = {}
        self.lastv = {}
    
    def onTick(self, tick):
        """收到行情TICK推送（必须由用户继承实现）"""
        super().onTick(tick)
        # 过滤涨跌停和集合竞价
        if tick.lastPrice == 0 or tick.askPrice1 == 0 or tick.bidPrice1 == 0:
            return
        symbol = tick.vtSymbol
        askP1 = tick.askPrice1
        bidP1 = tick.bidPrice1
        upperP = tick.upperLimit
        lowerP = tick.lowerLimit
        self.tickers[symbol] = tick
        self.askPrice1[symbol] = askP1
        self.bidPrice1[symbol] = bidP1
        self.upPrice[symbol] = upperP
        self.lowPrice[symbol] = lowerP
        self.midPrice[symbol] = (bidP1 + askP1) / 2.0
        if (self.widget is not None) and (not self.excSymbol == ''):
            self.widget.signal.emit()
        if self.lastv.get(tick.vtSymbol) is not None:
            self.lastvolume[tick.vtSymbol] = tick.volume - self.lastv.get(tick.vtSymbol)
            self.lastv[tick.vtSymbol] = tick.volume
        elif self.lastv.get(tick.vtSymbol) is None:
            self.lastv[tick.vtSymbol] = tick.volume
        self.putEvent()

    # self.output(self.tickers)

    def findOpenPrice(self, price):
        """找开仓仓单，开仓委托中返回数量，没有返回0"""
        a = 0
        for oid in self.openOrderInfo:
            oinfo = self.openOrderInfo[oid]
            if round(oinfo[1] / self.mPrice) == round(price / self.mPrice):
                a = oinfo[2] + a
        return a

    def findclosePrice(self, price):
        """找平仓单，开仓委托中返回数量，没有返回0"""
        a = 0
        for oid in self.closeOrderInfo:
            oinfo = self.closeOrderInfo[oid]
            if round(oinfo[1] / self.mPrice) == round(price / self.mPrice):
                a = oinfo[2] + a
        return a

    def onTrade(self, trade, log=False):
        super().onTrade(trade)
        symbol: str = self.symbolList[0]

        position = self.get_position(symbol)

        self.posL: int = position.long.position
        self.posS: int = position.short.position

        self.putEvent()

    def onInit(self) -> None:
        super().onInit()
        self.getGui()

    def onStart(self):
        super().onStart()
        self.lastvolume = {}
        self.symExMap = dict(zip(self.symbolList, self.exchangeList))
        self.excSymbol = self.symbolList[0]
        self.widget.show_signal.emit()

    def onStop(self):
        super().onStop()

    def buyS0(self, price, s, e, v):
        """买开合约"""
        orderID = self.buy(price, v, s, e)

    def shortS0(self, price, s, e, v):
        orderID = self.short(price, v, s, e)

    def buyclosetodayS0(self, price, s, e, v):
        """买平今合约"""

        orderID = self.sendOrder(CTAORDER_COVER_TODAY, price, v, s, e, )

    def buycloseS0(self, price, s, e, v):
        """买平昨合约"""
        orderID = self.sendOrder(CTAORDER_COVER, price, v, s, e, )

    def shortclosetodayS0(self, price, s, e, v):
        """买平今合约"""
        orderID = self.sendOrder(CTAORDER_SELL_TODAY, price, v, s, e, )

    def shortcloseS0(self, price, s, e, v):
        """买平昨合约"""
        orderID = self.sendOrder(CTAORDER_SELL, price, v, s, e, )

    def onOrder(self, order, log=True):
        super().onOrder(order, log)
        self.output(f'委托：{order.orderID} | {order.exchange} | {order.vtSymbol}')
        if order.price in self.buyid and order.status == '未成交':
            self.buyid[order.price].append(order.orderID)
        elif order.price not in self.buyid and order.status == '未成交':
            self.buyid[order.price] = [order.orderID]
        if order.price in self.buyid and order.status == '已撤销' and order.orderID in self.buyid[order.price]:
            self.buyid[order.price].remove(order.orderID)
        elif order.price in self.buyid and order.status == '全部成交' and order.orderID in self.buyid[order.price]:
            self.buyid[order.price].remove(order.orderID)
        if order.offset == '开仓':
            self.openOrderInfo[order.orderID] = [ORDER_LONG, order.price, order.totalVolume - order.tradedVolume]
        elif order.offset == '平仓' or order.offset == '平今':
            self.closeOrderInfo[order.orderID] = [ORDER_CLOSE, order.price, order.totalVolume - order.tradedVolume]
        if order.status == '已撤销' and order.orderID in self.openOrderInfo:
            del self.openOrderInfo[order.orderID]
        elif order.status == '已撤销' and order.orderID in self.closeOrderInfo:
            del self.closeOrderInfo[order.orderID]

        if (not self.widget is None) and (not self.excSymbol == ''):
            self.widget.signal.emit()


class TradingWidget1(QWidget):
    """简单下单组件"""

    directionList = ['开仓', '平仓', '平今']

    signal = QtCore.pyqtSignal()
    load_data_signal = QtCore.pyqtSignal()
    show_signal = QtCore.pyqtSignal()

    def __init__(self, strategy, parent=None):
        """Constructor"""
        super().__init__(parent)
        self.strategy: Demo_sendOrder = strategy
        self.symbol = ''
        self.strFormula = None
        self.started = True
        # 添加交易接口
        self.initUi()
        self.signal.connect(self.updateTick)
        self.show_signal.connect(self.show_ui)
        self.started = True

    def initUi(self):
        """初始化界面"""
        self.setWindowTitle('下单板' + self.strategy.name)
        self.setMaximumWidth(400)
        # 左边部分
        # labelPFormula = QLabel('中间价公式')
        # labelPFormula.setObjectName('whiteLabel'))
        labelHedge = QLabel('交易所')
        labelHedge.setObjectName('whiteLabel')
        labelName = QLabel('交易合约')
        labelName.setObjectName('whiteLabel')
        labelDirection = QLabel('报价方向')
        labelDirection.setObjectName('whiteLabel')
        labelPrice = QLabel('报单价格')
        labelPrice.setObjectName('whiteLabel')
        # labelSpread = QLabel('报价宽度')
        # labelSpread.setObjectName('whiteLabel'))
        # labelSSpread = QLabel('宽度限制')
        # labelSSpread.setObjectName('whiteLabel'))
        labelVolume = QLabel('报价数量')
        labelVolume.setObjectName('whiteLabel')
        # labelhe = QLabel('是否开启对冲')
        # labelhe.setObjectName('whiteLabel'))

        self.linePFormula = QLineEdit()
        self.instrument_id_input = QLineEdit()
        self.exchange_input = QLineEdit()
       # self.linehe = QLineEdit()

        self.comboDirection = QComboBox()
        self.comboDirection.addItems(self.directionList)
        self.comboDirection.currentIndexChanged.connect(self.dirChg)

      #  self.linehe = QComboBox()
        #self.linehe.addItems(self.hedgeList)
       # self.linehe.currentIndexChanged.connect(self.dirChg2)

        self.spinPrice = QDoubleSpinBox()
        self.spinPrice.setDecimals(4)
        self.spinPrice.setMinimum(0)
        self.spinPrice.setMaximum(100000000)
        self.spinPrice.setValue(self.strategy.P)
        self.spinPrice.valueChanged.connect(self.priceChg)

        # self.spinSpread = QDoubleSpinBox()
        # self.spinSpread.setDecimals(4)
        # self.spinSpread.setMinimum(0)
        # self.spinSpread.setMaximum(100000000)
        # self.spinSpread.setValue(self.strategy.pSpread)
        # self.spinSpread.valueChanged.connect(self.priceChg)

        self.spinVolume = QSpinBox()
        self.spinVolume.setMinimum(1) # 界面最小下单手数
        self.spinVolume.setMaximum(100000000)
        self.spinVolume.setValue(self.strategy.volume)
        self.spinVolume.valueChanged.connect(self.volumeChg)

        gridleft = QGridLayout()
        # gridleft.addWidget(labelPFormula, 0, 0)
        gridleft.addWidget(labelHedge, 0, 0)
        gridleft.addWidget(labelName, 1, 0)
        gridleft.addWidget(labelDirection, 2, 0)
        gridleft.addWidget(labelPrice, 3, 0)
        #  gridleft.addWidget(labelSpread, 5, 0)
        # gridleft.addWidget(labelSSpread, 6, 0)
        gridleft.addWidget(labelVolume, 4, 0)
       # gridleft.addWidget(labelhe, 5, 0)

        gridleft.addWidget(self.exchange_input, 0, 1)
        # gridleft.addWidget(self.instrument_id_input, 1, 1)
        gridleft.addWidget(self.instrument_id_input, 1, 1)
        gridleft.addWidget(self.comboDirection, 2, 1)
        gridleft.addWidget(self.spinPrice, 3, 1)
        # gridleft.addWidget(self.spinSpread, 5, 1)
        gridleft.addWidget(self.spinVolume, 4, 1)
      #  gridleft.addWidget(self.linehe, 5, 1)

        # 右边部分
        self.labelBid: List[QLabel] = []
        self.labelAsk: List[QLabel] = []
        self.labelBidP: List[QPushButton] = []
        self.labelAskP: List[QPushButton] = []
        self.labelBidV: List[QLabel] = []
        self.labelAskV: List[QLabel] = []

        for i in range(5):
            # lbidp = QLabel()
            lbidp = QPushButton()
            lbidp.setObjectName('redButton')
            self.labelBidP.append(lbidp)
            self.labelBidP[i].setMinimumWidth(60)
            self.labelBidP[i].clicked.connect(self.ccancel)

            #   laskp = QLabel()
            laskp = QPushButton()
            laskp.setObjectName('greenButton')
            self.labelAskP.append(laskp)
            self.labelAskP[i].setMinimumWidth(60)
            self.labelAskP[i].clicked.connect(self.ccancel)
            lbidv = QLabel()
            # lbidv = QPushButton()
            lbidv.setObjectName('darkBlueBackLabel')
            self.labelBidV.append(lbidv)

            #  self.labelBidV[i].clicked.connect(self.cancel)

            laskv = QLabel()
            #  laskv = QPushButton()
            laskv.setObjectName('darkBlueBackLabel')
            self.labelAskV.append(laskv)
            #  self.labelAskV[i].clicked.connect(self.cancel)
            lbid = QLabel(f'买{i + 1}')
            lbid.setObjectName('redLabel')
            self.labelBid.append(lbid)
            lask = QLabel(f'卖{i + 1}')
            lask.setObjectName('greenLabel')
            self.labelAsk.append(lask)

        labelLast = QLabel('最新')
        labelLast.setObjectName('blueLabel')
        self.labelLastPrice = QPushButton()
        # self.labelLastPrice = QLabel()
        self.labelLastPrice.setObjectName('blueBackLabel')
        self.labelReturn = QLabel()
        # self.labelReturn = QPushButton()
        self.labelReturn.setObjectName('darkBlueBackLabel')
        # self.labelLastPrice.append(labelLast)

        self.labelLastPrice.setMinimumWidth(60)
        self.labelReturn.setMinimumWidth(60)

        gridRight = QGridLayout()
        for i in range(5):
            gridRight.addWidget(self.labelAsk[5 - i - 1], i, 0)
            gridRight.addWidget(self.labelBid[i], 5 + i + 1, 0)
            gridRight.addWidget(self.labelAskP[5 - i - 1], i, 1)
            gridRight.addWidget(self.labelBidP[i], 5 + i + 1, 1)
            gridRight.addWidget(self.labelAskV[5 - i - 1], i, 2)
            gridRight.addWidget(self.labelBidV[i], 5 + i + 1, 2)
        gridRight.addWidget(labelLast, 5, 0)
        gridRight.addWidget(self.labelLastPrice, 5, 1)
        gridRight.addWidget(self.labelReturn, 5, 2)
        labelLM = QLabel('交易合约多单持仓:')
        labelSM = QLabel('交易合约空单持仓:')
        labelLH = QLabel('对冲合约多单持仓:')
        labelSH = QLabel('对冲合约空单持仓:')
        labelLM.setObjectName('redLabel')
        labelSM.setObjectName('greenLabel')
        labelLH.setObjectName('redLabel')
        labelSH.setObjectName('greenLabel')
        labelLM.setAlignment(Qt.AlignRight)
        labelSM.setAlignment(Qt.AlignRight)
        labelLH.setAlignment(Qt.AlignRight)
        labelSH.setAlignment(Qt.AlignRight)
        self.labelLMV = QLabel('')
        self.labelSMV = QLabel('')
        self.labelLHV = QLabel('')
        self.labelSHV = QLabel('')
        self.labelPNLMV = QLabel('')
        self.labelPNLHV = QLabel('')
        self.labelLMV.setObjectName('darkBlueBackLabel')
        self.labelSMV.setObjectName('darkBlueBackLabel')
        self.labelLHV.setObjectName('darkBlueBackLabel')
        self.labelSHV.setObjectName('darkBlueBackLabel')
        gridDown = QGridLayout()
        gridDown.addWidget(labelLM, 1, 0)
        gridDown.addWidget(labelSM, 2, 0)
        gridDown.addWidget(labelLH, 1, 2)
        gridDown.addWidget(labelSH, 2, 2)
        gridDown.addWidget(self.labelPNLMV, 0, 1)
        gridDown.addWidget(self.labelPNLHV, 0, 3)
        gridDown.addWidget(self.labelLMV, 1, 1)
        gridDown.addWidget(self.labelSMV, 2, 1)
        gridDown.addWidget(self.labelLHV, 1, 3)
        gridDown.addWidget(self.labelSHV, 2, 3)

        # 发单按钮
        self.buttonSendOrder = QPushButton('买入')
        self.buttonChgMode = QPushButton('卖出')
        # self.buttonHeadgeMode = QPushButton('不做对冲(点击-立即对冲)')
        # self.buttonCancelAll = QPushButton('一律开仓(点击-优先平仓)')

        size = self.buttonSendOrder.sizeHint()
        self.buttonSendOrder.setMinimumHeight(size.height() * 2)  # 把按钮高度设为默认两倍
        self.buttonChgMode.setMinimumHeight(size.height() * 2)  # 把按钮高度设为默认两倍
        #  self.buttonHeadgeMode.setMinimumHeight(size.height() * 2)  # 把按钮高度设为默认两倍
        #   self.buttonCancelAll.setMinimumHeight(size.height() * 2)
        self.buttonSendOrder.setObjectName('redButton')
        self.buttonChgMode.setObjectName('greenButton')
        # self.buttonHeadgeMode.setObjectName('greenButton'))
        #  self.buttonCancelAll.setObjectName('greenButton'))

        # 整合布局
        hbox = QHBoxLayout()
        hbox.addLayout(gridleft)
        hbox.addLayout(gridRight)

        vbox = QVBoxLayout()
        vbox.addLayout(hbox)
        vbox.addLayout(gridDown)
        vbox.addStretch()
        hbox0 = QHBoxLayout()
        hbox0.addWidget(self.buttonSendOrder)
        # hbox0.addWidget(self.buttonCancelAll)
        hbox1 = QHBoxLayout()
        hbox1.addWidget(self.buttonChgMode)
        #  hbox1.addWidget(self.buttonHeadgeMode)
        vbox.addLayout(hbox0)
        vbox.addLayout(hbox1)
        self.setLayout(vbox)

        # 关联更新
        self.buttonSendOrder.clicked.connect(self.startOrderbuy)
        # self.buttonCancelAll.clicked.connect(self.startOrder)
        self.buttonChgMode.clicked.connect(self.startOrdershort)
        # self.buttonHeadgeMode.clicked.connect(self.startOrder)
        self.exchange_input.returnPressed.connect(self.update_symbol_exch)
        self.instrument_id_input.returnPressed.connect(self.update_symbol_exch)
        self.hide()

    def show_ui(self) -> None:
        self.show()

    def dirChg(self, index):
        """报单方向变化"""
        # 读取组件数据
        try:
            orderDir = self.directionList[index]
            if orderDir == '开仓':
                self.strategy.orderDir = ORDER_LONG
            elif orderDir == '平仓':
                self.strategy.orderDir = ORDER_CLOSE
            elif orderDir == '平今':
                self.strategy.orderDir = ORDER_CLOSETODAY
            self.strategy.putEvent()
        except:
            pass

    def volumeChg(self, value):
        """报单量变化"""
        # 读取组件数据
        try:
            #  self.strategy.output(orderdir)
            self.updateTick()
            self.strategy.putEvent()
        except:
            pass

    def priceChg(self, value):
        """价格变化"""
        # 读取组件数据
        try:
            self.updateTick()
            # self.strategy.p = value
            self.strategy.putEvent()
        except:
            pass

    def startOrderbuy(self):
        """开始报单"""
        self.strategy.started = True
        self.strategy.trading = True
        self.started = True
        self.strategy.output('已发单')
        #  self.strategy.pSpread = self.spinSpread.value()
        self.strategy.volume = self.spinVolume.value()
        # self.spinSpread.setSingleStep(self.strategy.mPrice)
        self.spinPrice.setSingleStep(self.strategy.mPrice)

        if self.strategy.he == '否' and self.strategy.orderDir == ORDER_LONG:
            self.strategy.buyS0(self.spinPrice.value(), self.instrument_id_input.text(), self.exchange_input.text(),
                                self.spinVolume.value())
            self.strategy.output('发单完成')
        elif self.strategy.he == '否' and self.strategy.orderDir == ORDER_CLOSE:
            self.strategy.buycloseS0(self.spinPrice.value(), self.instrument_id_input.text(),
                                     self.exchange_input.text(), self.spinVolume.value())
            self.strategy.output('发单完成')
        elif self.strategy.he == '否' and self.strategy.orderDir == ORDER_CLOSETODAY:
            self.strategy.buyclosetodayS0(self.spinPrice.value(), self.instrument_id_input.text(),
                                          self.exchange_input.text(), self.spinVolume.value())
            self.strategy.output('发单完成')

        self.strategy.putEvent()

    def startOrdershort(self):
        """开始报单"""
        self.strategy.started = True
        self.strategy.trading = True
        self.started = True
        self.strategy.output('已发单')
        #  self.strategy.pSpread = self.spinSpread.value()
        self.strategy.volume = self.spinVolume.value()
        # self.spinSpread.setSingleStep(self.strategy.mPrice)
        self.spinPrice.setSingleStep(self.strategy.mPrice)
        if self.strategy.he == '否' and self.strategy.orderDir == ORDER_LONG:
            self.strategy.shortS0(self.spinPrice.value(), self.instrument_id_input.text(),
                                  self.exchange_input.text(), self.spinVolume.value())
            self.strategy.output('发单完成')
        elif self.strategy.he == '否' and self.strategy.orderDir == ORDER_CLOSE:
            self.strategy.shortcloseS0(self.spinPrice.value(), self.instrument_id_input.text(),
                                       self.exchange_input.text(), self.spinVolume.value())
            self.strategy.output('发单完成')
        elif self.strategy.he == '否' and self.strategy.orderDir == ORDER_CLOSETODAY:
            self.strategy.shortclosetodayS0(self.spinPrice.value(), self.instrument_id_input.text(),
                                            self.exchange_input.text(), self.spinVolume.value())
            self.strategy.output('发单完成')

        self.strategy.putEvent()

    def updateTick(self):
        """更新行情"""
        s = self.strategy
        if not self.started:
            return
        try:
            #  mmPrice = round((s.mmPrice + s.pOffset) / s.mPrice) * s.mPrice
            if len(self.instrument_id_input.text()) >= 3:
                tick: TickData = s.tickers.get(self.instrument_id_input.text())
                if not tick:
                    return
                # self.spinPrice.setValue(tick.lastPrice)
                askPL = [tick.askPrice1, tick.askPrice2, tick.askPrice3, tick.askPrice4, tick.askPrice5]
                bidPL = [tick.bidPrice1, tick.bidPrice2, tick.bidPrice3, tick.bidPrice4, tick.bidPrice5]
                askVL = [tick.askVolume1, tick.askVolume2, tick.askVolume3, tick.askVolume4, tick.askVolume5]
                bidVL = [tick.bidVolume1, tick.bidVolume2, tick.bidVolume3, tick.bidVolume4, tick.bidVolume5]
                avMap = dict([(ap, av) for av, ap in zip(askVL, askPL)])
                bvMap = dict([(bp, bv) for bv, bp in zip(bidVL, bidPL)])
                # 清空行情显示
                for i in range(5):
                    askPL[i] = askPL[0] + i * s.mPrice
                    bidPL[i] = bidPL[0] - i * s.mPrice
                    askVL[i] = avMap.get(askPL[i], '*')
                    bidVL[i] = bvMap.get(bidPL[i], '*')
                    self.labelAskP[i].setText(str(askPL[i]))
                    self.labelBidP[i].setText(str(bidPL[i]))
                    self.labelAskV[i].setText(f'{askVL[i]}|{s.findOpenPrice(askPL[i]) + s.findclosePrice(askPL[i])}')
                    self.labelBidV[i].setText(f'{bidVL[i]}|{s.findOpenPrice(bidPL[i]) + s.findclosePrice(askPL[i])}')

                    if not s.findOpenPrice(askPL[i]) == 0:
                        self.labelAskV[i].setStyleSheet("color:green;")
                    else:
                        self.labelAskV[i].setStyleSheet("color:white;")
                    if not s.findOpenPrice(bidPL[i]) == 0:
                        self.labelBidV[i].setStyleSheet("color:red;")
                    else:
                        self.labelBidV[i].setStyleSheet("color:white;")
                    if s.mmPrice == bidPL[i]:
                        self.labelBidV[i].setStyleSheet("color:yellow;")
                    elif s.mmPrice == askPL[i]:
                        self.labelAskV[i].setStyleSheet("color:yellow;")
                self.labelLastPrice.setText(str(tick.lastPrice))
                self.labelReturn.setText(str(s.lastvolume.get(self.instrument_id_input.text())))
                self.labelReturn.setStyleSheet("color:white;")
                # price = s.pOffset
                #  self.labelReturn.setText(str(price))
                self.labelLMV.setText(str(s.posL))
                self.labelSMV.setText(str(s.posS))
                self.labelLHV.setText(str(s.poshL))
                self.labelSHV.setText(str(s.poshS))
        except:
            s.output(traceback.format_exc())

    def clear(self):
        """清空数据"""
        pass

    def closeEvent(self, evt):
        """关闭"""
        if self.strategy.trading:
            self.strategy.output('只能在停止策略时自动关闭')
        else:
            self.hide()
        evt.ignore()

    def update_symbol_exch(self):
        """合约和交易所修改事件"""
        self.strategy.unSubSymbol()
        instrument_id = self.instrument_id_input.text()
        exchange = self.exchange_input.text()
        if all([instrument_id, exchange]):
            self.strategy.symbolList = [instrument_id]
            self.strategy.exchangeList = [exchange]
            self.strategy.subSymbol()
            self.strategy.output(f'交易所和合约已切换，合约：{instrument_id}，交易所：{exchange}')
            self.strategy.excSymbol = instrument_id
            self.strategy.excexchange = exchange

            #: 换合约时重新设置 UI 显示的持仓
            self.strategy.manage_position()
            long_position: int = self.strategy.ypos0L.get(instrument_id, 0) + self.strategy.tpos0L.get(instrument_id, 0)
            short_position: int = self.strategy.ypos0S.get(instrument_id, 0) + self.strategy.tpos0S.get(instrument_id, 0)
            self.strategy.posL = long_position
            self.strategy.posS = short_position
        else:
            self.strategy.output('请填写好交易所和合约再回车')

    def ccancel(self):
        """撤单事件"""
        try:
            for i in range(5):
                a = self.strategy.buyid.get(float(self.labelBidP[i].text()))
                b = self.strategy.buyid.get(float(self.labelAskP[i].text()))
                if b is not None:
                    for m in b:
                        self.strategy.cancelOrder(m)
                if a is not None:
                    for n in a:
                        self.strategy.cancelOrder(n)
        except:
            pass
