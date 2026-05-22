"""
=============================================================
  ai_analyst.py — محلل Claude AI العميق
  
  يضيف طبقة تفكير فوق الخوارزميات الكلاسيكية:
  - يستلم بيانات الشموع + نتائج الخوارزميات
  - يرسلها لـ Claude API
  - يحصل على تحليل عميق بالعربية مع قرار نهائي
  - يدمج قرار Claude مع قرار الخوارزميات (Hybrid Decision)
  - كاش ذكي لتوفير التكلفة
  
  المكونات:
  1. MarketContext     — تجميع كل البيانات في سياق واحد
  2. ClaudeAnalyst     — التواصل مع Claude API
  3. HybridDecision    — دمج Claude + الخوارزميات
  4. AnalysisCache     — كاش لتجنب طلبات متكررة
=============================================================
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("AIAnalyst")

from bot_algorithms import (
    Candle, Signal, TrendEngine, SupportResistance,
    CandlePatterns, Indicators, VolatilityFilter, ConfluenceEngine
)

# ─────────────────────────────────────────────
#  هياكل البيانات
# ─────────────────────────────────────────────

@dataclass
class MarketContext:
    """يجمع كل بيانات السوق في سياق واحد لإرساله لـ Claude"""
    symbol:          str
    payout:          float
    current_price:   float
    candle_age_pct:  float
    balance:         float
    trade_duration:  int = 60

    # نتائج الخوارزميات
    trend:           dict = field(default_factory=dict)
    sr_zones:        dict = field(default_factory=dict)
    candle_patterns: dict = field(default_factory=dict)
    indicators:      dict = field(default_factory=dict)
    volatility:      dict = field(default_factory=dict)
    confluence:      Optional[Signal] = None

    # بيانات الشموع الأخيرة (آخر 10)
    recent_candles:  list = field(default_factory=list)

    # سجل الجلسة
    session_wins:    int = 0
    session_losses:  int = 0
    consecutive_losses: int = 0


@dataclass
class AIDecision:
    """قرار Claude AI النهائي"""
    direction:       str    # UP / DOWN / WAIT
    confidence:      int    # 0-100
    reasoning:       str    # التحليل التفصيلي
    key_factors:     list   # أهم 3 عوامل
    risk_assessment: str    # تقييم المخاطر
    entry_quality:   str    # "ممتاز" / "جيد" / "ضعيف"
    suggestion:      str    # نصيحة إضافية
    raw_response:    str = ""
    from_cache:      bool = False
    processing_ms:   int  = 0


@dataclass
class HybridSignal:
    """الإشارة المدمجة من الخوارزميات + Claude"""
    final_direction:  str
    final_confidence: float
    algo_direction:   str
    algo_score:       int
    ai_direction:     str
    ai_confidence:    int
    agreement:        bool      # هل اتفقا؟
    trade_size:       float
    full_analysis:    str       # التحليل الكامل للـ Telegram
    reasons:          list
    warnings:         list


# ─────────────────────────────────────────────
#  1. كاش التحليل
# ─────────────────────────────────────────────

class AnalysisCache:
    """
    كاش بسيط في الذاكرة.
    يمنع إرسال نفس التحليل مرتين خلال فترة قصيرة.
    TTL = 45 ثانية (أقل من مدة الشمعة)
    """

    def __init__(self, ttl: int = 45):
        self._cache: dict[str, tuple[float, AIDecision]] = {}
        self.ttl = ttl
        self.hits  = 0
        self.misses = 0

    def _key(self, ctx: MarketContext) -> str:
        """مفتاح فريد بناءً على الشموع الأخيرة"""
        candle_sig = json.dumps(ctx.recent_candles[-5:], sort_keys=True)
        raw = f"{ctx.symbol}:{ctx.current_price:.5f}:{candle_sig}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def get(self, ctx: MarketContext) -> Optional[AIDecision]:
        key = self._key(ctx)
        entry = self._cache.get(key)
        if entry and time.time() - entry[0] < self.ttl:
            self.hits += 1
            decision = entry[1]
            decision.from_cache = True
            return decision
        self.misses += 1
        return None

    def set(self, ctx: MarketContext, decision: AIDecision):
        key = self._key(ctx)
        self._cache[key] = (time.time(), decision)

    def clear_expired(self):
        now = time.time()
        self._cache = {
            k: v for k, v in self._cache.items()
            if now - v[0] < self.ttl
        }

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        rate  = self.hits / total * 100 if total > 0 else 0
        return {"hits": self.hits, "misses": self.misses, "hit_rate": round(rate, 1)}


# ─────────────────────────────────────────────
#  2. محلل Claude AI
# ─────────────────────────────────────────────

class ClaudeAnalyst:
    """
    يرسل بيانات السوق لـ Claude ويستقبل تحليلاً عميقاً.
    
    يستخدم claude-sonnet-4-20250514 — أسرع وأرخص مع دقة ممتازة.
    يطلب JSON منظم لسهولة المعالجة.
    """

    MODEL   = "claude-sonnet-4-20250514"
    MAX_TOK = 800

    SYSTEM_PROMPT = """أنت محلل تداول خبير متخصص في الخيارات الثنائية قصيرة المدة.
مهمتك: تحليل بيانات السوق المقدمة واتخاذ قرار دخول دقيق.

قواعد التحليل:
- ركز على التقاطع بين عدة إشارات (Confluence)
- الترند الأقوى يطغى على الإشارات الضعيفة
- الشمعة عند مستوى S/R مع مؤشر ذروة = إشارة قوية جداً
- الدوجي والتعارض = انتظار
- لا تدخل إذا كانت الإشارات متضاربة بشكل كبير

أجب دائماً بـ JSON فقط، بدون أي نص خارجه، بهذا الشكل الدقيق:
{
  "direction": "UP أو DOWN أو WAIT",
  "confidence": رقم من 0 إلى 100,
  "reasoning": "تحليل تفصيلي بالعربية في 2-3 جمل",
  "key_factors": ["عامل 1", "عامل 2", "عامل 3"],
  "risk_assessment": "منخفض أو متوسط أو عالٍ",
  "entry_quality": "ممتاز أو جيد أو ضعيف",
  "suggestion": "نصيحة مختصرة للمتداول"
}"""

    def __init__(self,
                 api_key: str = None,
                 cache_ttl: int = 45,
                 max_retries: int = 2):
        self.api_key    = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.cache      = AnalysisCache(ttl=cache_ttl)
        self.max_retries = max_retries
        self._client = None
        self.total_calls = 0
        self.total_cost_usd = 0.0  # تقريبي

    def _get_client(self):
        if not self._client:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    def _build_prompt(self, ctx: MarketContext) -> str:
        """يبني prompt منظم من السياق"""
        # تلخيص الشموع
        candles_text = ""
        for i, c in enumerate(ctx.recent_candles[-8:], 1):
            direction = "⬆" if c.get("close", 0) > c.get("open", 0) else "⬇"
            candles_text += (
                f"  {i}. {direction} O:{c.get('open',0):.5f} "
                f"C:{c.get('close',0):.5f} "
                f"H:{c.get('high',0):.5f} "
                f"L:{c.get('low',0):.5f}\n"
            )

        # تلخيص المؤشرات
        ind = ctx.indicators
        rsi  = ind.get("rsi", "—")
        stoch = ind.get("stochastic", {})
        macd  = ind.get("macd", {})
        bb    = ind.get("bollinger", {})

        # تلخيص الترند
        tr = ctx.trend
        sr = ctx.sr_zones
        cp = ctx.candle_patterns
        vol = ctx.volatility

        # الإشارة من الخوارزميات
        algo_sig = ""
        if ctx.confluence:
            s = ctx.confluence
            algo_sig = (
                f"\n**قرار الخوارزميات:** {s.direction} | "
                f"نقاط: {s.score}/18 | ثقة: {s.confidence}%\n"
                f"أسباب: {', '.join(s.reasons[:3])}"
            )

        return f"""**بيانات السوق للتحليل:**

الزوج: {ctx.symbol}
السعر الحالي: {ctx.current_price:.5f}
نسبة العائد: {ctx.payout}%
عمر الشمعة الحالية: {ctx.candle_age_pct*100:.0f}%
مدة الصفقة: {ctx.trade_duration} ثانية
الرصيد: ${ctx.balance:.2f}

**آخر 8 شموع (الأحدث في الأسفل):**
{candles_text}

**الترند:**
- النوع: {tr.get('trend','—')} | القوة: {tr.get('strength','—')}
- ADX: {tr.get('adx','—')} | EMA8: {tr.get('ema8','—')} | EMA21: {tr.get('ema21','—')}
- HH/LL: {tr.get('hh_ll','—')}

**الدعم والمقاومة:**
- أقرب مقاومة: {sr.get('nearest_resistance','—')}
- أقرب دعم: {sr.get('nearest_support','—')}
- في منطقة مقاومة: {sr.get('in_resistance_zone','—')}
- في منطقة دعم: {sr.get('in_support_zone','—')}

**أنماط الشموع:**
- الأنماط: {', '.join(cp.get('patterns',[])) or 'لا يوجد'}
- إشارة النمط: {cp.get('signal','—')}
- قوة النمط: {cp.get('strength',0)}/5

**المؤشرات التقنية:**
- RSI(14): {rsi} {'⚠️ ذروة شراء' if isinstance(rsi, (int,float)) and rsi > 70 else '⚠️ ذروة بيع' if isinstance(rsi, (int,float)) and rsi < 30 else ''}
- Stochastic K: {stoch.get('k','—')} D: {stoch.get('d','—')} | تقاطع صعودي: {stoch.get('crossover_up','—')}
- MACD: {macd.get('macd','—')} | إشارة: {macd.get('direction','—')}
- Bollinger: إشارة {bb.get('signal','—')} | Squeeze: {bb.get('squeeze','—')}

**التقلب (ATR):**
- الحالة: {vol.get('reason','—')}
- النسبة: {vol.get('ratio','—')}

**جلسة التداول:**
- انتصارات: {ctx.session_wins} | خسائر: {ctx.session_losses}
- خسائر متتالية: {ctx.consecutive_losses}
{algo_sig}

حلل هذه البيانات وأعطني قرارك بـ JSON."""

    async def analyze(self, ctx: MarketContext) -> AIDecision:
        """
        يحلل السوق عبر Claude API.
        يستخدم الكاش إذا كان متاحاً.
        """
        # فحص الكاش أولاً
        cached = self.cache.get(ctx)
        if cached:
            log.debug("💾 Cache hit | %s", ctx.symbol)
            return cached

        start = time.time()

        for attempt in range(1, self.max_retries + 1):
            try:
                client = self._get_client()
                prompt = self._build_prompt(ctx)

                response = await client.messages.create(
                    model      = self.MODEL,
                    max_tokens = self.MAX_TOK,
                    system     = self.SYSTEM_PROMPT,
                    messages   = [{"role": "user", "content": prompt}]
                )

                raw_text = response.content[0].text.strip()
                ms = int((time.time() - start) * 1000)

                # تقدير التكلفة (Sonnet ~$3/M input + $15/M output)
                in_tok  = response.usage.input_tokens
                out_tok = response.usage.output_tokens
                cost    = (in_tok * 3 + out_tok * 15) / 1_000_000
                self.total_cost_usd += cost
                self.total_calls    += 1

                # تحليل الـ JSON
                decision = self._parse_response(raw_text, ms)

                # حفظ في الكاش
                self.cache.set(ctx, decision)

                log.info(
                    "🧠 Claude: %s | ثقة: %d%% | %dms | تكلفة: $%.4f",
                    decision.direction, decision.confidence, ms, cost
                )
                return decision

            except Exception as e:
                log.error("❌ Claude API خطأ %d: %s", e.status_code, e.message)
                if e.status_code == 429:  # Rate limit
                    await asyncio.sleep(10 * attempt)
                elif attempt == self.max_retries:
                    return self._fallback_decision("API error")
            except Exception as e:
                log.error("❌ Claude خطأ غير متوقع: %s", e)
                if attempt == self.max_retries:
                    return self._fallback_decision(str(e))
                await asyncio.sleep(2)

        return self._fallback_decision("max retries exceeded")

    def _parse_response(self, raw: str, ms: int) -> AIDecision:
        """يحلل الـ JSON من Claude"""
        try:
            # تنظيف إذا كان هناك markdown
            clean = raw.replace("```json", "").replace("```", "").strip()
            # أحياناً يكون هناك نص قبل الـ JSON
            start = clean.find("{")
            end   = clean.rfind("}") + 1
            if start >= 0 and end > start:
                clean = clean[start:end]

            data = json.loads(clean)

            return AIDecision(
                direction       = str(data.get("direction", "WAIT")).upper(),
                confidence      = int(data.get("confidence", 50)),
                reasoning       = str(data.get("reasoning", "—")),
                key_factors     = list(data.get("key_factors", [])),
                risk_assessment = str(data.get("risk_assessment", "متوسط")),
                entry_quality   = str(data.get("entry_quality", "جيد")),
                suggestion      = str(data.get("suggestion", "—")),
                raw_response    = raw,
                processing_ms   = ms,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            log.warning("⚠️ فشل تحليل JSON من Claude: %s | الرد: %s", e, raw[:100])
            # محاولة استخراج الاتجاه من النص
            direction = "WAIT"
            for d in ("UP", "DOWN"):
                if d in raw.upper():
                    direction = d
                    break
            return AIDecision(
                direction=direction, confidence=50,
                reasoning=raw[:200], key_factors=[],
                risk_assessment="متوسط", entry_quality="جيد",
                suggestion="تحقق من البيانات", raw_response=raw,
                processing_ms=ms
            )

    @staticmethod
    def _fallback_decision(reason: str) -> AIDecision:
        """قرار افتراضي عند فشل API"""
        return AIDecision(
            direction="WAIT", confidence=0,
            reasoning=f"تعذّر الحصول على تحليل AI: {reason}",
            key_factors=["فشل AI — اعتمد على الخوارزميات فقط"],
            risk_assessment="عالٍ", entry_quality="ضعيف",
            suggestion="اعتمد على نتيجة الخوارزميات الكلاسيكية",
        )

    @property
    def cost_summary(self) -> str:
        return (
            f"إجمالي استدعاءات Claude: {self.total_calls} | "
            f"التكلفة التقريبية: ${self.total_cost_usd:.4f} | "
            f"كاش: {self.cache.stats}"
        )


# ─────────────────────────────────────────────
#  3. القرار المدمج (Hybrid)
# ─────────────────────────────────────────────

class HybridDecision:
    """
    يدمج قرار الخوارزميات الكلاسيكية مع قرار Claude AI.
    
    منطق الدمج:
    ┌─────────────────┬────────────────┬──────────────────┐
    │ الخوارزميات    │ Claude AI       │ القرار النهائي   │
    ├─────────────────┼────────────────┼──────────────────┤
    │ UP              │ UP             │ UP (قوي جداً)    │
    │ DOWN            │ DOWN           │ DOWN (قوي جداً)  │
    │ UP              │ DOWN           │ WAIT (تعارض)     │
    │ UP/DOWN         │ WAIT           │ WAIT (حذر)       │
    │ WAIT            │ UP/DOWN        │ WAIT (انتظار)    │
    │ UP score≥6      │ UP conf≥70     │ UP (ممتاز)       │
    └─────────────────┴────────────────┴──────────────────┘
    """

    # أوزان الدمج
    W_ALGO = 0.55   # وزن الخوارزميات
    W_AI   = 0.45   # وزن Claude AI

    def __init__(self,
                 min_algo_score:    int   = 4,
                 min_ai_confidence: int   = 60,
                 require_agreement: bool  = True):
        self.min_algo_score    = min_algo_score
        self.min_ai_confidence = min_ai_confidence
        self.require_agreement = require_agreement

    def decide(self,
               algo_signal: Signal,
               ai_decision: AIDecision,
               balance:     float = 1000.0) -> HybridSignal:

        algo_dir = algo_signal.direction
        ai_dir   = ai_decision.direction
        agree    = (algo_dir == ai_dir) and algo_dir != "WAIT"

        warnings = list(algo_signal.warnings)
        reasons  = list(algo_signal.reasons)

        # ── منطق الدمج ──────────────────────────
        if ai_decision.from_cache:
            warnings.append("⚡ تحليل AI من الكاش")

        # كلاهما يتفقان على نفس الاتجاه
        if agree:
            final_dir = algo_dir
            # دمج نسب الثقة
            algo_norm = algo_signal.confidence / 100
            ai_norm   = ai_decision.confidence / 100
            final_conf = (algo_norm * self.W_ALGO + ai_norm * self.W_AI) * 100
            reasons.append(
                f"🧠 Claude يؤكد: {ai_dir} (ثقة {ai_decision.confidence}%)"
            )
            for f in ai_decision.key_factors[:2]:
                reasons.append(f"  • {f}")

        # تعارض بين الاثنين
        elif algo_dir != "WAIT" and ai_dir != "WAIT" and algo_dir != ai_dir:
            final_dir  = "WAIT"
            final_conf = 0.0
            warnings.append(
                f"⚠️ تعارض: الخوارزمية={algo_dir} | AI={ai_dir} — انتظار"
            )

        # الخوارزميات لديها إشارة لكن AI تقول WAIT
        elif algo_dir != "WAIT" and ai_dir == "WAIT":
            if algo_signal.score >= 6:
                # ثقة عالية بالخوارزميات — نكمل لكن بحجم أصغر
                final_dir  = algo_dir
                final_conf = algo_signal.confidence * 0.75
                warnings.append("🤔 AI محايد — نسبة الثقة مخفضة")
            else:
                final_dir  = "WAIT"
                final_conf = 0.0
                warnings.append("⏸ AI يوصي بالانتظار")

        # AI لديها إشارة لكن الخوارزميات WAIT
        elif algo_dir == "WAIT" and ai_dir != "WAIT":
            final_dir  = "WAIT"
            final_conf = 0.0
            warnings.append("⏸ الخوارزميات لا تؤكد إشارة AI")

        # كلاهما WAIT
        else:
            final_dir  = "WAIT"
            final_conf = 0.0

        # ── التحقق من الحد الأدنى ─────────────────
        if final_dir != "WAIT":
            if algo_signal.score < self.min_algo_score:
                final_dir  = "WAIT"
                final_conf = 0.0
                warnings.append(
                    f"نقاط الخوارزمية ({algo_signal.score}) أقل من الحد ({self.min_algo_score})"
                )
            elif ai_decision.confidence < self.min_ai_confidence and not ai_decision.from_cache:
                warnings.append(
                    f"⚠️ ثقة AI منخفضة ({ai_decision.confidence}%) — حجم مخفض"
                )
                final_conf *= 0.8

        # ── حجم الصفقة ────────────────────────────
        if final_dir == "WAIT":
            trade_size = 0.0
        else:
            # حجم مبني على الثقة المدمجة
            conf_ratio = min(final_conf / 100, 1.0)
            if conf_ratio >= 0.75:
                size_pct = 0.03   # 3% عند ثقة عالية
            elif conf_ratio >= 0.55:
                size_pct = 0.02   # 2% عند ثقة متوسطة
            else:
                size_pct = 0.01   # 1% عند ثقة منخفضة
            trade_size = round(balance * size_pct, 2)
            trade_size = max(1.0, min(trade_size, balance * 0.05))

        # ── بناء التحليل الكامل للـ Telegram ────────
        full_analysis = self._build_telegram_message(
            final_dir, final_conf, algo_signal, ai_decision,
            agree, trade_size
        )

        return HybridSignal(
            final_direction  = final_dir,
            final_confidence = round(final_conf, 1),
            algo_direction   = algo_dir,
            algo_score       = algo_signal.score,
            ai_direction     = ai_dir,
            ai_confidence    = ai_decision.confidence,
            agreement        = agree,
            trade_size       = trade_size,
            full_analysis    = full_analysis,
            reasons          = reasons,
            warnings         = warnings,
        )

    @staticmethod
    def _build_telegram_message(
        direction: str, confidence: float,
        algo: Signal, ai: AIDecision,
        agree: bool, trade_size: float
    ) -> str:
        icon   = "🟢" if direction == "UP" else "🔴" if direction == "DOWN" else "⏸"
        arrow  = "⬆️ صعود" if direction == "UP" else "⬇️ نزول" if direction == "DOWN" else "انتظار"
        agree_icon = "✅ اتفاق" if agree else "⚠️ تعارض"

        # شريط الثقة
        filled = int(confidence / 10)
        bar    = "█" * filled + "░" * (10 - filled)

        # جودة الدخول
        quality_icon = {
            "ممتاز": "🏆", "جيد": "👍", "ضعيف": "⚠️"
        }.get(ai.entry_quality, "📊")

        msg = (
            f"{icon} *إشارة مدمجة AI + خوارزميات* {icon}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *القرار: {arrow}*\n"
            f"📊 `{bar}` {confidence:.0f}%\n"
            f"💰 حجم الصفقة: `${trade_size:.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 *الخوارزميات:* {algo.direction} | نقاط {algo.score}/18\n"
            f"🧠 *Claude AI:* {ai.direction} | ثقة {ai.confidence}%\n"
            f"🤝 *الاتفاق:* {agree_icon}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*📝 تحليل Claude:*\n"
            f"_{ai.reasoning}_\n"
        )

        if ai.key_factors:
            msg += "\n*🔑 العوامل الرئيسية:*\n"
            for f in ai.key_factors[:3]:
                msg += f"  • {f}\n"

        msg += (
            f"\n{quality_icon} *جودة الدخول:* {ai.entry_quality}\n"
            f"⚡ *المخاطر:* {ai.risk_assessment}\n"
        )

        if ai.suggestion:
            msg += f"💡 *نصيحة:* _{ai.suggestion}_\n"

        if ai.from_cache:
            msg += f"\n_⚡ تحليل محفوظ مؤقتاً_"

        return msg


# ─────────────────────────────────────────────
#  4. واجهة التكامل الرئيسية
# ─────────────────────────────────────────────

class AIAnalystPipeline:
    """
    الواجهة الرئيسية — تربط كل شيء:
    Candles → Algorithms → Claude → HybridDecision
    
    يُستخدم من main.py بدلاً من ConfluenceEngine مباشرة
    """

    def __init__(self,
                 api_key:          str   = None,
                 min_algo_score:   int   = 4,
                 min_ai_confidence: int  = 60,
                 require_agreement: bool = True,
                 cache_ttl:        int   = 45,
                 enable_ai:        bool  = True):

        self.claude  = ClaudeAnalyst(api_key=api_key, cache_ttl=cache_ttl)
        self.hybrid  = HybridDecision(
            min_algo_score    = min_algo_score,
            min_ai_confidence = min_ai_confidence,
            require_agreement = require_agreement,
        )
        self.enable_ai = enable_ai

    async def analyze(self,
                      candles:       list[Candle],
                      current_price: float,
                      symbol:        str,
                      payout:        float,
                      balance:       float,
                      candle_age_pct: float = 0.0,
                      trade_duration: int   = 60,
                      session_wins:   int   = 0,
                      session_losses: int   = 0,
                      consecutive_losses: int = 0) -> HybridSignal:
        """
        التحليل الكامل:
        1. تشغيل جميع الخوارزميات
        2. تجميع السياق
        3. إرسال لـ Claude AI
        4. دمج القرارات
        """
        if len(candles) < 20:
            return self._insufficient_data_signal()

        # 1. تشغيل الخوارزميات
        trend_data  = TrendEngine(candles).analyze()
        sr_data     = SupportResistance(candles).find_zones(current_price)
        cp_data     = CandlePatterns(candles).analyze()
        ind_data    = Indicators(candles).analyze()
        vol_data    = VolatilityFilter(candles).check()

        algo_engine = ConfluenceEngine(
            candles        = candles,
            current_price  = current_price,
            payout         = payout,
            balance        = balance,
            candle_age_pct = candle_age_pct,
        )
        algo_signal = algo_engine.run()

        # 2. إذا AI معطل — أرجع نتيجة الخوارزميات فقط
        if not self.enable_ai or not self.claude.api_key:
            log.info("⚠️ AI معطل — الخوارزميات فقط")
            return HybridSignal(
                final_direction  = algo_signal.direction,
                final_confidence = algo_signal.confidence,
                algo_direction   = algo_signal.direction,
                algo_score       = algo_signal.score,
                ai_direction     = "WAIT",
                ai_confidence    = 0,
                agreement        = False,
                trade_size       = algo_signal.trade_size,
                full_analysis    = self._algo_only_message(algo_signal),
                reasons          = algo_signal.reasons,
                warnings         = algo_signal.warnings + ["🤖 AI معطل — نتيجة الخوارزميات فقط"],
            )

        # 3. بناء السياق لـ Claude
        recent_raw = [
            {"open": c.open, "close": c.close,
             "high": c.high, "low": c.low}
            for c in candles[-10:]
        ]
        ctx = MarketContext(
            symbol           = symbol,
            payout           = payout,
            current_price    = current_price,
            candle_age_pct   = candle_age_pct,
            balance          = balance,
            trade_duration   = trade_duration,
            trend            = trend_data,
            sr_zones         = sr_data,
            candle_patterns  = cp_data,
            indicators       = ind_data,
            volatility       = vol_data,
            confluence       = algo_signal,
            recent_candles   = recent_raw,
            session_wins     = session_wins,
            session_losses   = session_losses,
            consecutive_losses = consecutive_losses,
        )

        # 4. استدعاء Claude
        ai_decision = await self.claude.analyze(ctx)

        # 5. دمج القرارات
        hybrid = self.hybrid.decide(algo_signal, ai_decision, balance)

        log.info(
            "🎯 Hybrid: %s | conf=%.1f%% | algo=%s(%d) | ai=%s(%d%%) | اتفاق=%s",
            hybrid.final_direction, hybrid.final_confidence,
            hybrid.algo_direction, hybrid.algo_score,
            hybrid.ai_direction, hybrid.ai_confidence,
            "✅" if hybrid.agreement else "❌"
        )

        return hybrid

    @staticmethod
    def _insufficient_data_signal() -> HybridSignal:
        return HybridSignal(
            final_direction="WAIT", final_confidence=0,
            algo_direction="WAIT", algo_score=0,
            ai_direction="WAIT", ai_confidence=0,
            agreement=False, trade_size=0.0,
            full_analysis="⏳ بيانات غير كافية — انتظر تجميع الشموع",
            reasons=[], warnings=["بيانات غير كافية (أقل من 20 شمعة)"],
        )

    @staticmethod
    def _algo_only_message(sig: Signal) -> str:
        icon = "🟢" if sig.direction == "UP" else "🔴" if sig.direction == "DOWN" else "⏸"
        return (
            f"{icon} *إشارة الخوارزميات (بدون AI)*\n"
            f"القرار: {sig.direction} | نقاط: {sig.score}/18 | ثقة: {sig.confidence}%\n"
            + "\n".join(f"• {r}" for r in sig.reasons[:4])
        )

    @property
    def stats(self) -> dict:
        return {
            "total_ai_calls":    self.claude.total_calls,
            "total_cost_usd":    round(self.claude.total_cost_usd, 4),
            "cache":             self.claude.cache.stats,
            "ai_enabled":        self.enable_ai,
        }


# ─────────────────────────────────────────────
#  دمج مع data_layer — استبدال ConfluenceEngine
# ─────────────────────────────────────────────

def create_ai_signal_handler(
    pipeline,
    ai_pipeline: AIAnalystPipeline,
    on_hybrid_signal,
    manager=None,
):
    """
    ينشئ handler يُستخدم بدلاً من on_signal_received في main.py
    يمرر الإشارة عبر AI قبل إرسالها
    """
    async def handler(algo_signal):
        candles = pipeline.buffer.candles
        if len(candles) < 20:
            return

        sess_wins   = manager.stats.wins   if manager else 0
        sess_losses = manager.stats.losses if manager else 0
        cons_losses = manager.stats.consecutive_losses if manager else 0

        hybrid = await ai_pipeline.analyze(
            candles            = candles,
            current_price      = pipeline.buffer.current_price,
            symbol             = pipeline.data_settings.symbol,
            payout             = pipeline.data_settings.payout,
            balance            = pipeline.data_settings.balance,
            candle_age_pct     = pipeline.buffer.candle_age_pct,
            trade_duration     = int(os.getenv("TRADE_DURATION", "60")),
            session_wins       = sess_wins,
            session_losses     = sess_losses,
            consecutive_losses = cons_losses,
        )

        # تحويل HybridSignal → Signal للتوافق مع TradeManager
        from bot_algorithms import Signal
        unified_signal = Signal(
            direction   = hybrid.final_direction,
            score       = hybrid.algo_score,
            confidence  = hybrid.final_confidence,
            reasons     = hybrid.reasons,
            warnings    = hybrid.warnings,
            trade_size  = hybrid.trade_size,
            details     = {"hybrid": True, "ai_analysis": hybrid.full_analysis},
        )

        await on_hybrid_signal(unified_signal, hybrid)

    return handler


# ─────────────────────────────────────────────
#  اختبار
# ─────────────────────────────────────────────

async def _test():
    """اختبار بدون API key حقيقي"""
    from bot_algorithms import Candle
    import random; random.seed(42)

    candles = [
        Candle(
            open  = 0.8600 + i * 0.0003,
            close = 0.8604 + i * 0.0003,
            high  = 0.8610 + i * 0.0003,
            low   = 0.8596 + i * 0.0003,
            volume= 1200
        )
        for i in range(30)
    ]

    # اختبار بدون AI
    pipeline = AIAnalystPipeline(
        enable_ai=False,
        min_algo_score=1
    )
    result = await pipeline.analyze(
        candles       = candles,
        current_price = 0.8690,
        symbol        = "EURUSD-OTC",
        payout        = 88.0,
        balance       = 500.0,
    )
    print(f"✅ Hybrid (بدون AI): {result.final_direction} | ثقة: {result.final_confidence}%")
    print(f"   الاتفاق: {result.agreement}")
    print(f"   حجم الصفقة: ${result.trade_size}")
    print(f"   تحذيرات: {result.warnings}")
    print()

    # اختبار الكاش
    cache = AnalysisCache(ttl=60)
    ctx = MarketContext(
        symbol="TEST", payout=88, current_price=0.86,
        candle_age_pct=0.1, balance=500,
        recent_candles=[{"open":0.86,"close":0.861,"high":0.862,"low":0.859}]
    )
    fake_decision = AIDecision(
        direction="UP", confidence=75,
        reasoning="اختبار", key_factors=["عامل 1"],
        risk_assessment="منخفض", entry_quality="جيد",
        suggestion="ادخل"
    )
    cache.set(ctx, fake_decision)
    cached = cache.get(ctx)
    print(f"✅ Cache: from_cache={cached.from_cache} | hits={cache.hits}")
    print(f"   Stats: {cache.stats}")

    print("\n✅ جميع اختبارات AI Analyst نجحت")


if __name__ == "__main__":
    asyncio.run(_test())
