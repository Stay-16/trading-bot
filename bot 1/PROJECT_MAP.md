# 🤖 بوت التداول الذكي — PROJECT MAP

## 📁 هيكل المشروع

```
bot 1/
├── main.py                    # نقطة الدخول — BotCore, handlers, Telegram
├── .env                       # الإعدادات الحية (API keys, tolerances)
├── .env.example               # قالب الإعدادات
├── session.json               # جلسة Quotex الحية
├── bot.log                    # سجل التشغيل
├── trading_model.pkl          # نموذج ML المدرب
│
├── gemini_verifier.py         # [جديد] — توليد شارت + تحليل Gemini البصري
├── indicators_library.py      # [جديد] — RSI, ADX, Ichimoku, OBV, ATR, Volume Profile
├── market_regime.py           # [جديد] — ADX-based regime + استراتيجية
├── backtesting.py             # [جديد] — محاكاة تاريخية كاملة
│
├── bot_algorithms.py          # ConfluenceEngine (14 مؤشر), Signal, Candle
├── data_layer.py              # Quotex connection, DataPipeline, polling
├── trade_executor.py          # TradeManager, DB, execution
├── advanced_ai.py             # ML model (RandomForest, GB, XGBoost, LSTM)
├── ai_analyst.py              # Claude AI analyst (مستبدل بـ Gemini)
├── webapp_server.py           # FastAPI + WebSocket للـ WebApp
├── webapp_index.html          # Frontend (phone-frame chat + dashboard)
├── ui.py                      # Telegram UI (keyboards, captions, status)
├── telegram_alerts_pro.py     # ProMessageBuilder, ChartGenerator, History
├── tradingview_provider.py    # TradingView data
├── pairs_registry.py          # 76+ زوج مع الإعدادات
├── api_schemas.py             # Pydantic models
│
├── shared/
│   ├── decision_engine.py     # 7 مصادر قرار + أوزان
│   ├── risk_manager.py        # Kelly, drawdown, con. losses
│   ├── unified_signal.py      # SignalPackage, FusedResult
│   ├── auto_executor.py       # 4 Gates (score, ensemble, TV, Claude)
│   ├── adaptive_thresholds.py # Thresholds حسب حالة السوق
│   ├── portfolio_manager.py   # توزيع رأس المال
│   ├── self_optimizer.py      # تعلم مستمر
│   ├── db_reporter.py         # تقارير قاعدة البيانات
│   ├── asset_mapping.py       # ربط الأزواج بين Quotex/TradingView
│   ├── pair_scanner.py        # فحص جميع الأزواج
│   ├── broker_connection.py   # إدارة اتصال الوسيط
│   └── execution_service.py   # تنفيذ الصفقات
│
├── run_webapp.py              # مشغل WebApp
├── START_BOT.bat              # سكربت بدء التشغيل
├── docker-compose.yml         # نشر Docker
├── images/                    # صور الإشارات (buy/, sell/)
└── requirements.txt           # التبعيات
```

---

## 🧠 بنية القرار — 7 مصادر

| المصدر | الوزن | الوظيفة |
|--------|--------|----------|
| `confluence_engine` | **0.25** | ConfluenceEngine (14 مؤشر) |
| `ai_model` | **0.18** | AdvancedAI (RandomForest + GB + XGB) |
| `traditional` | **0.18** | TradingView signal |
| `lstm` | **0.15** | LSTM التنبؤي |
| `trend_filter` | **0.12** | فلتر الاتجاه |
| `volatility_filter` | **0.07** | فلتر التقلب |
| `candle_pattern` | **0.05** | أنماط الشموع |

---

## 🔄 الدورة الخماسية (Gemini)

```
🎯 المستخدم يختار زوج + مدة
  │
  ▼
① ConfluenceEngine (14 مؤشر) ← رصد الفرصة رقمياً
  │
  ▼
② mplfinance ← توليد شارت (Bollinger, EMA9/21, Volume)
  │
  ▼
③ Gemini 2.5 Flash API ← إرسال الشارت + التقرير الفني
  │
  ▼
④ Gemini يحلل بصرياً (Price Action) + رقمياً
  │
  ├─ CONFIRMED → ×1.05 ثقة → إشارة → تليجرام
  └─ CANCEL    → "🛑 ألغيت" + سبب
```

---

## ⚙️ ConfluenceEngine — 14 مؤشر داخلي

| المؤشر | الوزن | الإعدادات |
|---------|--------|-----------|
| TrendEngine | 2.0 | ADX 14, EMA 9/21, BB 20/2, MACD 12/26/9 |
| VolumeAnalysis | 1.5 | MA 20, ratio>1.5x |
| MomentumOscillator | 1.5 | RSI 14, Stoch 14/3, ROC 10 |
| MultiTimeframe | 1.5 | 5m (×5), 15m (×15) |
| HeikinAshi | 1.2 | — |
| DivergenceDetector | 1.2 | lookback 30, RSI<30/>70 |
| DynamicSR | 1.0 | lookback 50, tolerance 0.1% |
| FibonacciLevels | 1.0 | 0/23.6/38.2/50/61.8/78.6/100 |
| IchimokuCloud | 1.0 | 9/26/52/26 |
| VWAP | 1.0 | >2σ extreme |
| MarketRegimeDetector | 1.0 | ADX≥25, ATR%≥1.5% |
| MarketStructure | 1.0 | lookback 20 |
| OrderBlocks | 1.0 | lookback 30 |
| TrendLines | 1.0 | lookback 40 |
| SessionFilter | 0.5 | London 7-16, NY 12-21 UTC |
| CandlePatterns | 0.8 | Doji, Hammer, Engulfing, إلخ |

---

## 🌍 MarketRegimeFilter (حالة السوق)

| الحالة | ADX | تعديل الثقة | الاستراتيجية |
|---------|-----|------------|-------------|
| strong_trend | ≥40 | +10 | trend_following |
| trending | 25-39 | +5 | trend_following |
| volatile | ATR≥1.5% | -10 | breakout_retest |
| ranging | <20 | -5 | mean_reversion |
| transitional | 20-24 | 0 | confluence |

---

## 🛡️ FusedRiskManager

| الإعداد | القيمة |
|---------|--------|
| Risk per trade | 2% |
| Max daily loss | 10% |
| Max cons. losses | 3 |
| Kelly cap | 25% |
| Max concurrent | 3 |
| Max exposure | 30% |
| Kelly multipliers | 0→1.0, 1→0.5, 2→0.25, 3→0.0 |
| Trade amounts | min $1, max $200 |

---

## 📊 SignalStrengthScore

| النطاق | التصنيف |
|--------|--------|
| ≥80 | VERY_STRONG |
| ≥65 | STRONG |
| ≥45 | MODERATE |
| ≥25 | WEAK |
| <25 | VERY_WEAK |

---

## 🔙 BacktestingEngine

| الإعداد | القيمة |
|---------|--------|
| Initial balance | $1,000 |
| Payout | 88% |
| Risk per trade | 2% |
| Min score | 6 |
| Max cons loss | 3 |
| المقاييس | Sharpe, Sortino, MaxDD, WinRate, ProfitFactor, Expectancy |

---

## 🌐 WebApp (FastAPI + LightweightCharts)

| الإعداد | القيمة |
|---------|--------|
| Host/Port | 127.0.0.1:8081 |
| Cache Analysis | 4s |
| Cache Markets | 8s |
| Cache Health | 12s |
| Trade-ready | score ≥12 |
| AI ready | conf≥70 & score≥10 |

---

## 📞 Telegram Interface

| الأمر/الزر | الوظيفة |
|-----------|---------|
| `/start` | تشغيل تلقائي → Dashboard |
| 🎯 تحليل يدوي | اختيار زوج + مدة + تأكيد |
| ✅ تأكيد وبدء التداول | Confluence + MarketRegime + Gemini |
| 🔄 Next Signal! | إشارة جديدة (نفس الدورة) |
| 📊 Dashboard | إحصائيات + أزرار سريعة |
| `/backtest` | محاكاة تاريخية |
| 🛑 إيقاف | إيقاف البوت |

---

## 📈 الإصدارات

| v | الميزات |
|---|---------|
| Base | Telegram + Quotex + ConfluenceEngine |
| +Indicators | Ichimoku, OBV, ADX, Volume Profile, ATR |
| +MarketRegime | ADX regime + auto-strategy |
| +Backtesting | BacktestingEngine + Sharpe/Sortino |
| +Manual Only | إزالة الإشارات التلقائية |
| +WAIT Fix | WAIT signals ترسل نصوصاً |
| +Gemini | تحليل بصري + رقمي 5 مراحل |
| +Next Signal | زر الإشارة التالية مع MarketRegime |
