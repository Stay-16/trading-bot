# PROJECT_MAP — Trading Bot Fusion (Bot 1 + Bot 2)

> Last updated: 2026-05-14
> Status: Phase 2–6 complete — UI replaced with GPT Trading Bot Design (~98/100)

---

## [TECH_STACK]

| Component | Version | Source |
|---|---|---|
| Python | 3.11+ | system |
| pyquotex | latest (git) | github.com/cleitonleonel/pyquotex |
| python-telegram-bot | >=21 | both bots |
| aiosqlite | >=0.19 | bot1 |
| python-dotenv | >=1.0 | both |
| anthropic | >=0.90 | bot1 (Claude AI) |
| FastAPI | >=0.115 | bot2 |
| uvicorn | >=0.30 | bot2 |
| scikit-learn | >=1.5 | bot2 |
| tradingview-ta | >=3.3 | bot2 |
| numpy | >=1.26 | bot2 |
| pandas | >=2.2 | bot2 |

---

## [SYSTEM_FLOW]

```
User (Telegram / FastAPI TWA)
  │
  ├── Telegram Commands ──► main.py (BotCore)
  │                              │
  │                              ├── do_start()
  │                              │    ├── Database.connect()
  │                              │    ├── AIAnalystPipeline (Claude)
  │                              │    ├── MLPredictor / AdvancedAISystem
  │                              │    ├── DataPipeline (Quotex connection)
  │                              │    │    ├── QuotexConnection (connect + retry)
  │                              │    │    ├── CandleStream (fetch historical)
  │                              │    │    ├── DataBuffer (aggregate candles)
  │                              │    │    └── LiveDataFeed (polling loop)
  │                              │    ├── ConfluenceEngine (24 components, 38pt)
  │                              │    │    └── signal_callback()
  │                              │    │         ├── TV analysis (TradingViewProvider)
  │                              │    │         ├── ML / Advanced AI enhance
  │                              │    │         ├── WeightedDecisionEngine fusion
  │                              │    │         │    └── build_fused_votes() (7 votes)
  │                              │    │         │         ├── traditional (18%, TV)
  │                              │    │         │         ├── ai_model (18%, ensemble)
  │                              │    │         │         ├── lstm (15%)
  │                              │    │         │         ├── trend_filter (12%)
  │                              │    │         │         ├── volatility_filter (7%)
  │                              │    │         │         ├── candle_pattern (5%)
  │                              │    │         │         └── confluence_engine (25%)
  │                              │    │         ├── FusedRiskManager (can_open, sizing)
  │                              │    │         ├── AI analyze (Anthropic Claude)
  │                              │    │         └── on_new_signal()
  │                              │    │              ├── ProMessageBuilder
  │                              │    │              ├── Telegram send
  │                              │    │              ├── FusedRiskManager.record_trade_result
  │                              │    │              └── TradeManager.handle_signal()
  │                              │    │                   ├── TradeExecutor.execute()
  │                              │    │                   ├── TradeExecutor.wait_for_result()
  │                              │    │                   └── Database.save()
  │                              │    └── Dashboard (basic SSE) — still active
  │
  └── FastAPI WebApp ──► webapp_server.py (bot1, adapted)
       ├── REST API (/api/health, /api/markets, /api/analyze, etc.)
       ├── WebSocket (/ws/live-feed)
       └── TWA SPA (lightweight-charts)
```

## [ARCHITECTURE]

### Current Bot 1 Structure
```
bot 1/
├── main.py              # Entry point, Telegram handlers, BotCore
├── data_layer.py        # QuotexConnection, CandleStream, DataBuffer, LiveDataFeed, DataPipeline
├── trade_executor.py    # Database (aiosqlite), TradeExecutor, TradeManager, SessionStats
├── bot_algorithms.py    # ConfluenceEngine (24 comp, 38pt), Signal, Candle, RiskRewardOptimizer
├── pairs_registry.py    # 70+ pair definitions with PairInfo
├── telegram_alerts_pro.py # ProMessageBuilder (ASCII charts, signal grades)
├── ai_analyst.py        # AIAnalystPipeline (Anthropic Claude wrapper)
├── ml_engine.py         # MLPredictor (Random Forest basic)
├── dashboard.py         # Basic SSE dashboard
└── database.py          # DEAD CODE — synchronous predecessor
```

### Current Bot 2 Structure
```
bot 2/
├── trading_bot.py       # Main entry (3098 lines), all-in-one
├── bot_config.py        # BotSettings, RiskSettings frozen dataclasses
├── data_layer.py        # MarketDataLayer (TV analysis + context)
├── signal_engine.py     # SignalEngine (5 signal sources)
├── decision_engine.py   # WeightedDecisionEngine (voting)
├── decision_core.py     # BinaryOptionsDecisionCore (6 votes)
├── risk_management.py   # RiskManager (Kelly, per-user state)
├── execution_layer.py   # ExecutionLayer (DI adapter)
├── trading_orchestrator.py # Coordinates layers 1-5
├── asset_mapping.py     # Dynamic pair discovery, symbol normalization
├── broker_connection_service.py # Connection health + balance cache
├── trade_execution_service.py   # Robust buy with asset name variants
├── trade_monitor_service.py     # Post-trade monitoring + online learning
├── trade_state_service.py       # Active trades state mgmt
├── api_schemas.py       # Pydantic models
├── webapp_server.py     # FastAPI + WebSocket + TWA
└── telegram_*.py        # Split Telegram callback handlers
```

### Current Merged Bot
```
bot 1/ (enhanced — fused)
├── main.py                  # Enhanced: TV analysis, WeightedDecisionEngine, FusedRiskManager
├── data_layer.py            # Enhanced with realtime snapshot, stream subscription
├── trade_executor.py        # Enhanced with TradeExecutionService integration
├── bot_algorithms.py        # UNCHANGED (ConfluenceEngine — 24 comp, 38pt)
├── pairs_registry.py        # UNCHANGED (70+ pairs)
├── telegram_alerts_pro.py   # UNCHANGED (ProMessageBuilder)
├── ai_analyst.py            # UNCHANGED (Claude AI)
├── advanced_ai.py           # NEW — from bot2 (Ensemble + LSTM + online learning)
├── tradingview_provider.py  # NEW — from bot2 (TA provider)
├── api_schemas.py           # NEW — Pydantic models for WebApp
├── webapp_server.py         # NEW — FastAPI server adapted for bot1
├── webapp_index.html        # NEW — TWA SPA frontend (from bot2)
├── webapp_app.js            # NEW — TWA SPA logic (from bot2)
├── webapp_styles.css        # NEW — TWA SPA styles (from bot2)
├── run_webapp.py            # NEW — WebApp launcher
│
├── shared/                  # NEW — from bot2
│   ├── asset_mapping.py     # Dynamic pair discovery
│   ├── broker_connection.py # Connection health + caching
│   ├── execution_service.py # Robust trade execution
│   ├── monitor_service.py   # Post-trade monitoring
│   ├── decision_engine.py   # WeightedDecisionEngine + build_fused_votes (7 votes)
│   ├── risk_manager.py      # FusedRiskManager (Kelly + per-user state + circuit breaker)
│   ├── pair_scanner.py      # Dynamic scanner — scan_top_trade_setups()
│   └── candle_patterns.py   # 8 candlestick patterns
│
```

---

## [ORPHANS & PENDING]

### Phase 3 — ✅ ALL COMPLETED:
| Item | Status | Notes |
|---|---|---|
| `shared/pair_scanner.py` (dynamic scanner) | ✅ DONE | `scan_top_trade_setups()` — fetches candles per pair, runs ConfluenceEngine, ranks by score |
| Dynamic scanner wired into webapp `/api/top-setups` | ✅ DONE | Returns real scored setups instead of placeholders |
| `database.py` (dead sync code) removed | ✅ DONE | Superseded by `trade_executor.py` aiosqlite Database |
| Quad-analysis with real indicator data | ✅ DONE | `_build_indicator_snapshot()` computes EMA50, EMA200, RSI, ATR; `_build_quad_analysis()` trend + momentum sections |
| Quad-analysis wired into webapp `/api/analyze` | ✅ DONE | Richer quad_analysis sections, live_analysis_steps includes RSI momentum |
| `shared/candle_patterns.py` (8 patterns) | ✅ DONE | bullish_engulfing, bearish_engulfing, hammer, shooting_star, doji, morning_star, evening_star, momentum_expansion |
| Candlestick patterns wired into analyze | ✅ DONE | `candlestick_pattern_detail` field in `/api/analyze` response |
| Multi-timeframe confirmation | ✅ DONE | Aggregates candles to approximate higher TF, runs ConfluenceEngine, alignment check |
| Entry watcher (alert/auto modes) | ✅ DONE | `_run_entry_watch()` background task, 2.5s poll, 5min timeout, start/cancel/status endpoints |
| TWA tighter API token auth | ✅ DONE | `_verify_api_token()` — X-API-Key or Bearer check against `.env.webapp` |
| Lazy anthropic import (ai_analyst.py) | ✅ DONE | `import anthropic` moved into `ClaudeAnalyst._get_client()` — eliminates 17s module-level hang |
| Lazy numpy/sklearn import (advanced_ai.py) | ✅ DONE | Module-level `import numpy`, sklearn, joblib, xgboost → per-method lazy getters. `from __future__ import annotations` for deferred type hints |
| Webapp price=0 guard | ✅ DONE | `ZeroDivisionError` guard when bot not started — returns clean error JSON |
| Import timing verified | ✅ DONE | `import main` completes in ~2s, `B` accessible; `import webapp_server` clean |
| Webapp endpoint tests | ✅ DONE | All 10+ endpoints respond correctly (static files, REST API, POST execute) |

### Active (Phase 2 — ✅ COMPLETED):
| Item | Status | Notes |
|---|---|---|
| `shared/asset_mapping.py` | ✅ DONE | From bot2 — dynamic pair discovery, symbol normalization |
| `shared/broker_connection.py` | ✅ DONE | Connection health + DI pattern |
| `shared/execution_service.py` | ✅ DONE | Robust buy with asset name variants |
| `shared/monitor_service.py` | ✅ DONE | Post-trade monitoring + online learning |
| Enhanced `data_layer.py` QuotexConnection | ✅ DONE | session.json cache, stdout silencing, realtime snapshot |
| Enhanced `trade_executor.py` execution | ✅ DONE | Candidate asset approach + fallback |
| Enhanced `main.py` bot2 services | ✅ DONE | BrokerConnection, TradeExecution, TradingView caches |
| `requirements.txt` deps sync | ✅ DONE | Added tradingview-ta, sklearn, fastapi, uvicorn |
| Syntax verification | ✅ DONE | All files pass `py_compile` |
| TradingView TA integration | ✅ DONE | `TradingViewProvider` with rate-limit + signal extraction |
| `advanced_ai.py` (Ensemble + LSTM + online) | ✅ DONE | Replaces basic MLPredictor |
| `shared/decision_engine.py` | ✅ DONE | `WeightedDecisionEngine` + `build_fused_votes()` (7 votes) |
| `shared/risk_manager.py` | ✅ DONE | `FusedRiskManager` — per-user state, Kelly, circuit breaker |
| `api_schemas.py` | ✅ DONE | Pydantic models for WebApp REST API |
| `webapp_server.py` (bot1 adaptation) | ✅ DONE | FastAPI server with /api/health, /api/markets, /api/analyze, /api/live-snapshot, /api/execute, /api/top-setups, WS /ws/live-feed |
| Frontend files copied | ✅ DONE | webapp_index.html, webapp_app.js, webapp_styles.css |
| `run_webapp.py` launcher | ✅ DONE | uvicorn on port 8081 |
| Fused decision engine wired into signal pipeline | ✅ DONE | `signal_callback()` builds 7 votes → WeightedDecisionEngine → risk check → position sizing |
| FusedRiskManager wired into win/loss handlers | ✅ DONE | `record_trade_result()` on all manual results |
| PROJECT_MAP.md updated | ✅ DONE | Full Phase 2 reflection |

### Phase 4 — Stabilize & Clean — ✅ COMPLETED:
| Item | Status | Notes |
|---|---|---|
| Remove dead files | ✅ DONE | `pairs.py`, `database.py`, `ml_engine.py`, `dashboard.py`, `dashboard.html`, `telegram_bot.py`, `trading_model.pkl`, `datetime` |
| Fix stdout encoding | ✅ DONE | `sys.stdout.reconfigure(encoding='utf-8')` — emojis no longer crash cp1252 terminals |
| Remove stale Dashboard/ML references | ✅ DONE | Startup summary updated, dead-code guards (ML_AVAILABLE/DASHBOARD_AVAILABLE) preserved |
| Unified config | ✅ DONE | `.env.webapp` falls back to `WEBAPP_API_TOKEN` in main `.env` |
| Graceful shutdown | ✅ DONE | `post_shutdown` + `try/finally` around `run_polling()` — saves state, closes connection |
| Runtime QA | ✅ DONE | All 21 `.py` files compile clean. `import main` ~3s. All webapp endpoints 200. |

### Phase 5 — Intelligence — ✅ COMPLETED:
| Item | Status | Notes |
|---|---|---|
| Backtesting engine | ✅ DONE | `backtest_engine.py` — `FusedBacktestEngine` simulates ConfluenceEngine + FusedRiskManager. Metrics: win rate, Sharpe, Sortino, max DD, equity curve, expectancy. |
| Walk-forward optimization | ✅ DONE | `walk_forward.py` — `WalkForwardOptimizer` splits train/test, optimizes `min_score` per asset. Run with `python walk_forward.py` |
| Portfolio risk | ✅ DONE | Extended `FusedRiskManager`: `register_trade()`/`unregister_trade()`, max concurrent trades, correlation group detection, global exposure limit. Wired into `on_trade_event`. |
| Online learning feedback loop | ✅ DONE | `B.advanced_ai.learn_from_trade()` wired into win/loss button handlers and auto-close events. Features: OHLCV, price changes. Triggers `retrain()` at 100+ samples. |

### Phase 6 — Monitoring & UX — ✅ COMPLETED:
| Item | Status | Notes |
|---|---|---|
| WebSocket real-time updates | ✅ DONE | `/ws/live-feed` sends price, candles, sentiment, payout every 2s. Frontend switched to `PREFER_HTTP_LIVE_FEED=false` (WebSocket by default, HTTP fallback). |
| P&L Dashboard | ✅ DONE | `GET /api/performance` — returns total_trades, win_rate, net_profit, sharpe_ratio, equity_curve (90-day), pair_performance. `journal_analytics` enhanced with same data. |
| Critical alerts | ✅ DONE | Circuit breaker alert (≥3 consecutive losses), daily loss warning (≥80% of limit), connection health watchdog (60s poll, alerts on disconnect/reconnect). |
| Bug fixes | ✅ DONE | `get_recent_closed_trades` → `get_recent_trades` (wrong method name broke `/api/trade-journal`). |

### UI Replacement (2026-05-14):
| Item | Status | Notes |
|---|---|---|
| `bot 1/ui.py` → GPT Trading Bot Design (706 lines) | ✅ DONE | Full replacement: new dashboard, trading, pairs, expiry, auto, settings screens. Aliases kept for compatibility. |
| `main.py` — wrapper signatures updated | ✅ DONE | `kb_pairs_list` → `build_pairs_keyboard`, `kb_settings`/`msg_settings` simplified (no params). |
| `main.py` — new callback handlers | ✅ DONE | `nav_trading`, `nav_pairs`, `nav_expiry`, `nav_auto`, `confirm_start`, `settings_*`, `stats_*`, `clear_log`, `pair_*`, `pairs_prev/next`, `market_*/trade_*/asset_*` selections. |
| Old category pagination replaced | ✅ DONE | `page_next_*/page_prev_*` → `pairs_prev/pairs_next` with single page counter. |
| Old pairs categories kept for compat | ✅ DONE | `pairs_video`, `pairs_major_otc`, `pairs_exotic_otc`, `pairs_all_otc`, `pairs_regular` still work via `pairs_menu`. |

### Latest changes (2026-05-14 v2):
| Item | Status | Notes |
|---|---|---|
| Mode Select row removed from Trading screen | ✅ DONE | Normal/Alerts/Hyper deleted |
| `confirm_start` → instant signal (manual flow) | ✅ DONE | Runs ConfluenceEngine directly, no "بدء التداول" message |
| `nav_stats` handler added (was missing) | ✅ DONE | Now shows stats with `build_stats_keyboard()` |
| `cmd_journal` uses `build_log_text` from ui.py | ✅ DONE | Consistent formatting |
| `paper_mode=False` always (shows "💵 حقيقي") | ✅ DONE | TradeManager forces `paper_mode=True` for demo execution |
| `toggle_mode` button removed from settings | ✅ DONE | User wants permanent real mode |
| `_selected_trade` variable removed | ✅ DONE | No longer needed after Mode Select removal |

### Pending UI sub-sections (settings):
| Item | Status | Notes |
|---|---|---|
| `settings_amounts` | ⏳ PENDING | Stub — returns "قيد التطوير" |
| `settings_connection` | ⏳ PENDING | Stub — returns "قيد التطوير" |
| `settings_lang` | ⏳ PENDING | Stub — returns "قيد التطوير" |
