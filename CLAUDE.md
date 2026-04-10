# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InfiniTrader (无限易) is a quantitative trading platform. This directory contains the **Python strategy layer** that runs inside the InfiniTrader desktop application (C++ host: `InfiniTrader.exe`). Strategies are loaded and executed by the host via an embedded Python interpreter.

- Python path: `D:\ProgramData\miniconda3\python.exe` (Python 3.13.11)
- Strategy source root: `pyStrategy/`
- Log files: `StraLog.txt`, `UserLog.txt`, `YYYYMMDD_Syslog.log`
- Config: `InfiniConfig.ini`, `corelib.ini`

## Two Strategy APIs (Legacy vs PythonGO)

The codebase has **two distinct strategy frameworks**. New strategies should use PythonGO.

### Legacy CTA API (`pyStrategy/ctaTemplate.py`)
- Base class: `CtaTemplate` — uses `ctaEngine` module (injected by host) and `INFINIGO` C extension
- Strategies in `pyStrategy/strategy/` use this API (e.g. `Demo_Strategy.py`)
- Uses `paramMap`/`varMap` dicts for parameter mapping to the UI
- Chinese-language constants: `CTAORDER_BUY = '买开'`, `CTAORDER_SHORT = '卖开'`, etc. (defined in `pyStrategy/ctaBase.py`)
- Includes `BarManager` (tick→KLine), `ArrayManager` (numpy array manager with talib indicators), `QtGuiSupport`, `KLWidget`
- K-line visualization built on PyQt5 + pyqtgraph with dark theme (qdarkstyle)

### PythonGO API (`pyStrategy/pythongo/`)
- Base class: `pythongo.base.BaseStrategy` — uses `pythongo.infini` wrapper module
- Parameters via Pydantic `BaseModel` (`BaseParams`); state via `BaseState`
- Cleaner type hints, English-language API (`send_order`, `auto_close_position`, `get_position`, etc.)
- Enum-based constants in `pythongo.const` (`OrderDirectionEnum`, `OrderOffsetEnum`)
- Data classes in `pythongo/classdef/` (`TickData`, `OrderData`, `TradeData`, `Position`, etc.)

## Architecture

```
InfiniTrader.exe (C++ host)
  ├── ctaEngine          ← Python module injected by host (legacy)
  ├── INFINIGO           ← C extension module injected by host (both APIs)
  └── pyStrategy/
       ├── ctaTemplate.py          ← Legacy CTA strategy base + BarManager + ArrayManager + KLWidget
       ├── ctaTemplate_option.py   ← Legacy option strategy base
       ├── option_template.py      ← Option pricing functions (BSM, Greeks)
       ├── language/               ← i18n: Chinese/English constants
       ├── pythongo/               ← PythonGO framework
       │   ├── base.py             ← BaseStrategy, BaseParams, BaseState
       │   ├── infini.py           ← Thin wrapper around INFINIGO
       │   ├── const.py            ← OrderDirectionEnum, OrderOffsetEnum
       │   ├── classdef/           ← Data models (TickData, OrderData, Position, etc.)
       │   ├── ui/                 ← Visual backtesting (BaseStrategy + KLWidget for pyqtgraph)
       │   ├── backtesting/        ← Backtesting engine, fake classes, scheduler
       │   ├── indicator.py        ← Technical indicator helpers
       │   └── option.py           ← Option-related functions
       ├── strategy/               ← Legacy demo strategies
       ├── demo/                   ← PythonGO demo strategies
       └── self_strategy/          ← User's custom strategies
```

## Key Patterns

### How strategies get loaded
The host (`InfiniTrader.exe`) embeds Python and injects `ctaEngine` and `INFINIGO` as built-in modules. Strategy files in `pyStrategy/` are loaded at runtime. Do not import these modules standalone — they only exist inside the host process.

### Mode detection (backtesting vs live)
```python
os.environ["PYTHONGO_MODE"] = "BACKTESTING"  # set by backtesting engine
```
When `INFINIGO` import fails, `pythongo/infini.py` falls back to `pythongo.backtesting.fake_class.INFINIGO`.

### Strategy lifecycle callbacks
Both APIs follow the same lifecycle: `on_init` → `on_start` → (trading loop) → `on_stop`
- **Legacy**: `onInit()`, `onStart()`, `onStop()`, `onTick()`, `onBar()`, `onTrade()`, `onOrder()`
- **PythonGO**: `on_init()`, `on_start()`, `on_stop()`, `on_tick()`, `on_trade()`, `on_order()`

### Order flow
- **Legacy**: `buy()`, `short()`, `sell()`, `cover()` → `sendOrder()` → `ctaEngine.sendOrder()`
- **PythonGO**: `send_order()` → `make_order_req()` → `infini.send_order()` → `INFINIGO.sendOrder()`
- Auto-close position: `auto_close_position()` handles SHFE/INE close-today vs close-yesterday logic

### K-line visualization (Legacy)
`ctaTemplate.py` auto-starts a Qt GUI thread (`setQtSp()` at module level). Strategies with `widgetClass` get a `KLWidget` with K-line chart (pyqtgraph + custom candlestick rendering). Data flows: strategy → `widget.recv_kline(data)` → signal → UI update.

### Backtesting (`pythongo/backtesting/`)
Entry point: `backtesting.run(config, strategy_cls, strategy_params, start_date, end_date, initial_capital)`.
Uses `FakeQtGuiSupport`/`FakeWidget` to replace real UI. Engine handles tick replay, order matching (price-based), P&L calculation.

## Language/i18n
Constants in `pyStrategy/language/` provide Chinese (`constant.py`) or English versions. `pyStrategy/vtConstant.py` dynamically imports from the current language module. The default is Chinese.

## Key Dependencies
- **numpy, pandas** — data handling
- **talib** — technical indicators (SMA, EMA, MACD, BOLL, RSI, CCI, etc.)
- **PyQt5, pyqtgraph** — K-line charting and UI
- **qdarkstyle** — dark theme for Qt
- **pydantic** — parameter validation (PythonGO)
- **scipy** — option pricing (BSM model)
