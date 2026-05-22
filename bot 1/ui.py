"""
ui.py - تصميم واجهة تيليغرام
مطابق لـ GPT Trading Bot Design
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

المسار اليدوي:  Dashboard → Trading → Pairs → Expiry → إشارة
المسار التلقائي: Dashboard → Auto (يختار الزوج والمدة تلقائياً)
"""

import os
import random
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")

# ══════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════

def _esc(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    special = r"\_*[]`~"
    return "".join(f"\\{c}" if c in special else c for c in text)

def _esc_html(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def kb(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text, callback_data=cb) for text, cb in row]
        for row in rows
    ])

def _sel(label: str, active: bool) -> str:
    return f"■ {label} ■" if active else label

# ══════════════════════════════════════════
#  الصور
# ══════════════════════════════════════════

def get_signal_image(direction: str) -> bytes | None:
    folder_key = direction.lower()
    if folder_key == "up":
        folder_key = "buy"
    elif folder_key == "down":
        folder_key = "sell"
    folder = os.path.join(IMAGES_DIR, folder_key)
    if not os.path.isdir(folder):
        return None
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
    ]
    if not files:
        return None
    path = os.path.join(folder, random.choice(files))
    with open(path, "rb") as f:
        return f.read()

# ══════════════════════════════════════════
#  1. DASHBOARD
# ══════════════════════════════════════════

def build_dashboard_text(
    is_running: bool,
    paper_mode: bool,
    win_rate: float,
    balance: float,
    symbol: str,
    price: float,
    uptime: str,
    ai_enabled: bool,
    ml_available: bool,
    total_signals: int = 0,
    wins: int = 0,
    losses: int = 0,
    trade_remaining: str = "",
) -> str:
    status   = "🟢 يعمل" if is_running else "🔴 متوقف"
    mode     = "📋 تجريبي" if paper_mode else "💵 حقيقي"
    ai_st    = "🧠 Claude AI" if ai_enabled else "⚙️ خوارزميات"
    ml_st    = " + 🤖 ML" if ml_available else ""
    wr       = win_rate if wins + losses > 0 else 98
    conf_bar = "█" * min(int(wr / 10), 10) + "░" * (10 - min(int(wr / 10), 10))
    timer    = f"\n  ⏱️ متبقي للصفقة: `{trade_remaining}`" if trade_remaining else ""
    return (
        f"🤖 *تداول ذكي v3* — 7 مصادر قرار\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {status}  |  {mode}\n"
        f"  📊 الزوج الحالي: `{symbol}`\n"
        f"  ⏱️ مدة التشغيل: `{uptime}`\n"
        f"  🎯 دقة الإشارات: `{conf_bar}` `{wr:.0f}%`\n"
        f"  {ai_st}{ml_st}\n"
        f"{timer}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  💰 الرصيد: `${balance:.2f}`\n"
        f"  📈 إشارات: `{total_signals}` | ✅ `{wins}` | ❌ `{losses}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  /scan — 🔍 مسح | /report — 📋 تقرير\n"
        f"  /accuracy — 🎯 دقة | /portfolio — 📊 محفظة"
    )

def build_dashboard_keyboard(
    is_running: bool,
    paper_mode: bool,
    auto_mode: bool = False,
) -> InlineKeyboardMarkup:
    if is_running:
        top_row = [
            InlineKeyboardButton("⏹ إيقاف", callback_data="stop"),
            InlineKeyboardButton(
                "🔄 إيقاف التلقائي" if auto_mode else "🤖 تلقائي",
                callback_data="stop_auto" if auto_mode else "nav_auto",
            ),
        ]
        analysis_row = [
            InlineKeyboardButton("🎯 تحليل يدوي", callback_data="nav_trading"),
        ]
    else:
        top_row = [
            InlineKeyboardButton("🔄 إعادة التشغيل", callback_data="start_bot"),
            InlineKeyboardButton("🤖 تلقائي",        callback_data="nav_auto"),
        ]
        analysis_row = [
            InlineKeyboardButton("🎯 تحليل يدوي", callback_data="nav_trading"),
        ]
    return InlineKeyboardMarkup([
        top_row,
        analysis_row,
        [
            InlineKeyboardButton("📊 الإحصائيات",     callback_data="nav_stats"),
            InlineKeyboardButton("📡 الحالة المباشرة", callback_data="nav_status"),
        ],
        [
            InlineKeyboardButton("🧾 سجل الصفقات", callback_data="nav_log"),
            InlineKeyboardButton("⚙️ الإعدادات",   callback_data="nav_settings"),
        ],
        [
            InlineKeyboardButton("🔍 مسح الأزواج", callback_data="cmd_scan"),
            InlineKeyboardButton("📋 تقرير",        callback_data="cmd_report"),
        ],
        [
            InlineKeyboardButton("🎯 الدقة",         callback_data="cmd_accuracy"),
            InlineKeyboardButton("📊 المحفظة",       callback_data="cmd_portfolio"),
            InlineKeyboardButton("🔄 تحسين",         callback_data="cmd_optimize"),
        ],
    ])

# ══════════════════════════════════════════
#  2. TRADING  (خطوة 1/3 في المسار اليدوي)
# ══════════════════════════════════════════

def build_trading_text(ai_symbol: str = "AUD/CAD (OTC)") -> str:
    return (
        f"⚙️ *Choose a chart type*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🤖 AI recommended asset:\n"
        f"  *{_esc(ai_symbol)}*\n\n"
        f"  • OTC, Live, Alert mode, Crypto, etc..\n"
        f"  /settings"
    )

def build_trading_keyboard(
    selected_market: str = "otc",
    selected_asset:  str = "forex",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↓ Charts Type ↓", callback_data="noop")],
        [
            InlineKeyboardButton(_sel("OTC",  selected_market == "otc"),  callback_data="market_otc"),
            InlineKeyboardButton(_sel("Live", selected_market == "live"), callback_data="market_live"),
        ],
        [InlineKeyboardButton("↓ Options Select ↓", callback_data="noop")],
        [
            InlineKeyboardButton(_sel("Currencies", selected_asset == "forex"),  callback_data="asset_forex"),
            InlineKeyboardButton(_sel("Crypto",     selected_asset == "crypto"), callback_data="asset_crypto"),
        ],
        [
            InlineKeyboardButton(_sel("Stocks",      selected_asset == "stocks"),      callback_data="asset_stocks"),
            InlineKeyboardButton(_sel("Indices",     selected_asset == "indices"),     callback_data="asset_indices"),
            InlineKeyboardButton(_sel("Commodities", selected_asset == "commodities"), callback_data="asset_commodities"),
        ],
        [InlineKeyboardButton("✅ Confirm your Choice ✅", callback_data="nav_pairs")],
        [InlineKeyboardButton("‹ رجوع", callback_data="nav_dashboard")],
    ])

# ══════════════════════════════════════════
#  3. PAIRS  (خطوة 2/3 في المسار اليدوي)
# ══════════════════════════════════════════

def build_pairs_text(ai_symbol: str = "AUD/CAD (OTC)", page: int = 0, total_pages: int = 3) -> str:
    return (
        f"⚙️ *Choose the asset below* ⚙️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🤖 AI recommended asset:\n"
        f"  *{_esc(ai_symbol)}*\n\n"
        f"  • OTC, Live, Alert mode, Crypto, etc..\n"
        f"  /settings"
    )

def build_pairs_keyboard(
    pairs,
    get_payout_fn,
    current_symbol: str,
    pair_pages: dict,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    total = len(pairs)
    start = page * page_size
    end   = min(start + page_size, total)
    items = (list(pairs.items()) if isinstance(pairs, dict) else list(pairs))[start:end]

    buttons = []
    row = []
    for i, (k, info) in enumerate(items):
        active = current_symbol == getattr(info, "quotex_symbol", k)
        label  = ("✓ " if active else "") + getattr(info, "display_name", k)
        row.append(InlineKeyboardButton(label, callback_data=f"pair_{k}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    total_pages = max(1, (total + page_size - 1) // page_size)
    buttons.append([
        InlineKeyboardButton("←", callback_data="pairs_prev" if page > 0 else "noop"),
        InlineKeyboardButton(f"{page + 1} / {total_pages}", callback_data="noop"),
        InlineKeyboardButton("→", callback_data="pairs_next" if end < total else "noop"),
    ])
    buttons.append([
        InlineKeyboardButton("✅ تأكيد الزوج", callback_data="nav_expiry"),
        InlineKeyboardButton("‹ رجوع",        callback_data="nav_trading"),
    ])
    return InlineKeyboardMarkup(buttons)

# ══════════════════════════════════════════
#  4. EXPIRY  (خطوة 3/3 في المسار اليدوي)
# ══════════════════════════════════════════

def build_expiry_text() -> str:
    return "⏳ *Choose the expiration time:*"

def build_expiry_keyboard(current_duration: int = 60) -> InlineKeyboardMarkup:
    def _b(v: int) -> InlineKeyboardButton:
        mark = "✓ " if v == current_duration else ""
        if v < 60:
            label = f"{mark}{v} seconds"
        elif v == 60:
            label = f"{mark}1 minute"
        else:
            label = f"{mark}{v // 60} minutes"
        return InlineKeyboardButton(label, callback_data=f"dur_{v}")

    return InlineKeyboardMarkup([
        [_b(3),   _b(5)],
        [_b(10),  _b(30)],
        [_b(60)],
        [_b(120), _b(180), _b(240)],
        [_b(300)],
        [_b(600), _b(900)],
        [
            InlineKeyboardButton("✅ تأكيد وبدء التداول", callback_data="confirm_start"),
            InlineKeyboardButton("‹ رجوع",               callback_data="nav_pairs"),
        ],
    ])

# ══════════════════════════════════════════
#  5. AUTO — التداول التلقائي
# ══════════════════════════════════════════

def build_auto_text(
    balance: float,
    symbol: str,
    duration: int,
    trade_size: float,
    ai_recommended: str = "",
) -> str:
    rec = f"  🤖 AI recommended: *{_esc(ai_recommended)}*\n" if ai_recommended else ""
    if duration < 60:
        dur_label = f"{duration}s"
    elif duration == 60:
        dur_label = "1 min"
    else:
        dur_label = f"{duration // 60} min"
    return (
        f"🤖 *التداول التلقائي*\n"
        f"  يعمل بذكاء اصطناعي متقدم\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  💰 الرصيد الحالي: *${balance:.2f}*\n\n"
        f"{rec}"
        f"  🎯 الزوج: `{symbol}`\n"
        f"  ⏱ المدة: `{dur_label}`\n"
        f"  💰 مبلغ الصفقة: `${trade_size:.2f}`\n"
        f"  🛡 حد الخسارة: `${balance * 0.05:.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  _البوت سيختار أفضل زوج ومدة تلقائياً_"
    )

def build_auto_keyboard(is_running: bool) -> InlineKeyboardMarkup:
    btn = ("⏹ إيقاف", "stop") if is_running else ("▶ تشغيل التلقائي", "auto_mode")
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(btn[0], callback_data=btn[1]),
            InlineKeyboardButton("⚙️ الإعدادات", callback_data="nav_settings"),
        ],
        [InlineKeyboardButton("‹ رجوع", callback_data="nav_dashboard")],
    ])

# ══════════════════════════════════════════
#  6. SIGNAL — رسالة الإشارة (بدون تغيير)
# ══════════════════════════════════════════

def build_signal_caption(
    direction: str,
    symbol: str,
    score: int,
    max_score: int,
    confidence: float,
    strength_grade: str,
    strength_icon: str,
    strength_label: str,
    trade_size: float,
    overlap_pct: int,
    success_pct: int,
    payout: float,
    reasons: list,
    warnings: list,
    timestamp: str = None,
    strength_pct: float = 0,
    context_session: str = "",
    context_trend: str = "",
) -> str:
    dir_display = direction.upper().replace("UP", "BUY").replace("DOWN", "SELL")
    emoji    = "🟢" if dir_display == "BUY" else "🔴" if dir_display == "SELL" else "⏸"
    conf_bar = "█" * int(confidence / 10) + "░" * (10 - int(confidence / 10))
    safe_reasons = [_esc(r) for r in reasons[:5]]
    top_reasons  = "\n".join(f"  • {r}" for r in safe_reasons) if reasons else "  —"
    warns = ""
    if warnings:
        warns = "\n⚠️ *تحذيرات:*\n" + "\n".join(f"  ⚠️ {_esc(w)}" for w in warnings[:3])
    ts = timestamp or datetime.now().strftime("%H:%M:%S")
    strength_line = f"  ▸ 💡 قوة: *{strength_pct:.0f}%*\n" if strength_pct > 0 else ""
    ctx = ""
    if context_session:
        ctx += f"\n◆━ *السياق* ━━━━━━━━━◆\n  🕐 `{ts}` | 📍 {context_session}\n"
        if context_trend:
            ctx += f"  📉 {context_trend}\n"
    return (
        f"{emoji} *{dir_display} SIGNAL*\n\n"
        f"⚙️ *Settings:*\n"
        f"  ▸ asset - *{symbol}*\n"
        f"  ▸ payout - *{payout:.0f}%*\n\n"
        f"📊 *Signal Strength:*\n"
        f"  ▸ Score: *{score}/{max_score}* {strength_icon} {strength_label}\n"
        f"{strength_line}"
        f"  ▸ Confidence: *`{conf_bar}`* *{confidence:.0f}%*\n"
        f"  ▸ Trade Size: *${trade_size:.2f}*\n\n"
        f"◆━━ *التوقعات* ━━━━━━━━◆\n"
        f"  ❌ تداخل: *{overlap_pct}%*\n"
        f"  ✅ نجاح: *{success_pct}%*\n\n"
        f"🔍 *Analysis in brief:*\n"
        f"{top_reasons}\n"
        f"{warns}"
        f"{ctx}"
    )

def build_signal_keyboard(is_running: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if is_running:
        rows.append([("🔄 Next Signal!", "signal")])
    rows.append([("‹ رجوع", "nav_dashboard")])
    return kb(rows)

# ══════════════════════════════════════════
#  7. STATS
# ══════════════════════════════════════════

def build_stats_text(
    total_signals: int,
    wins: int,
    losses: int,
    win_rate: float,
    balance: float,
    payout: float,
    consecutive_losses: int,
    consecutive_wins: int,
    uptime: str,
    today: dict = None,
) -> str:
    decided = wins + losses
    wr      = win_rate
    bar     = ("█" * max(0, min(10, int(wr / 10))) + "░" * (10 - max(0, min(10, int(wr / 10))))) if decided else "░" * 10
    net     = wins * (payout / 100) - losses
    wr_icon = "🟢" if wr >= 60 else "🟡" if wr >= 40 else "🔴"
    msg = (
        f"📈 *إحصائيات التداول*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  📨 إشارات: `{total_signals}`\n"
        f"  🎯 صفقات: `{decided}`\n"
        f"  ✅ ربح: `{wins}`  ❌ خسارة: `{losses}`\n"
        f"  {wr_icon} `{bar}` `{wr:.1f}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  💵 صافي: `{'+'if net>=0 else ''}{net:.2f}$`\n"
        f"  🔥 خسائر متتالية: `{consecutive_losses}`\n"
        f"  💰 الرصيد: `${balance:.2f}`\n"
        f"  ⏳ المدة: `{uptime}`\n"
    )
    if today and today.get("total", 0) > 0:
        pnl_icon = "🟢" if today["net_profit"] >= 0 else "🔴"
        msg += (
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  {today['wins']}✅  {today['losses']}❌\n"
            f"  📊 نجاح: `{today['win_rate']:.1f}%`\n"
            f"  {pnl_icon} صافي: `{'+'if today['net_profit']>=0 else ''}{today['net_profit']:.2f}$`\n"
        )
    return msg

def build_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 اليوم",   callback_data="stats_day"),
            InlineKeyboardButton("📅 الأسبوع", callback_data="stats_week"),
            InlineKeyboardButton("📅 الشهر",   callback_data="stats_month"),
        ],
        [InlineKeyboardButton("‹ رجوع", callback_data="nav_dashboard")],
    ])

# ══════════════════════════════════════════
#  8. STATUS
# ══════════════════════════════════════════

def build_status_text(
    is_running: bool,
    paper_mode: bool,
    is_connected: bool,
    ai_enabled: bool,
    ml_available: bool,
    symbol: str,
    payout: float,
    price: float,
    candles_count: int,
    candle_age_pct: float,
    balance: float,
    uptime: str,
) -> str:
    conn = "✅ متصل"    if is_connected else "🔴 منقطع"
    run  = "🟢 يعمل"   if is_running   else "🔴 متوقف"
    mode = "📋 تجريبي" if paper_mode   else "💵 حقيقي"
    age  = f"{candle_age_pct * 100:.0f}%" if candle_age_pct else "—"
    n    = candles_count
    bar  = "█" * min(n // 10, 10) + "░" * (10 - min(n // 10, 10))
    return (
        f"📡 *الحالة المباشرة*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  الحالة: {run}\n"
        f"  الوضع: {mode}\n"
        f"  🔌 Quotex: {conn}\n"
        f"  🧠 AI: {'🟢 نشط' if ai_enabled else '🔴 غير نشط'}\n"
        f"  🤖 ML: {'🟢 نشط' if ml_available else '🔴 غير نشط'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  📊 الزوج: `{symbol}`\n"
        f"  💰 العائد: `{payout:.0f}%`\n"
        f"  💲 السعر: `{price:.5f}`\n"
        f"  🕯 الشموع: `{bar}` `{n}/100`\n"
        f"  ⏱ عمر الشمعة: {age}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  💵 الرصيد: `${balance:.2f}`\n"
        f"  ⏳ التشغيل: `{uptime}`"
    )

def build_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 تحديث", callback_data="nav_status"),
            InlineKeyboardButton("‹ رجوع",   callback_data="nav_dashboard"),
        ],
    ])

# ══════════════════════════════════════════
#  9. LOG
# ══════════════════════════════════════════

def build_log_text(logs: list = None) -> str:
    text = "🧾 *سجل الصفقات*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if logs:
        for entry in logs[:10]:
            icon   = "✅" if entry.get("result") == "win" else "❌"
            pair   = entry.get("symbol", entry.get("pair", "—"))
            profit = entry.get("profit", 0)
            raw_ts = entry.get("opened_at", entry.get("time", ""))
            ts     = raw_ts.strftime("%H:%M") if hasattr(raw_ts, "strftime") else str(raw_ts)[:8]
            color  = "🟢" if (profit or 0) >= 0 else "🔴"
            text  += f"  {icon} `{pair}` {color} {profit:+.2f}  _{ts}_\n"
    else:
        text += "  لا توجد صفقات بعد\n"
    return text

def build_log_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 تحديث",     callback_data="nav_log"),
            InlineKeyboardButton("🗑️ مسح السجل", callback_data="clear_log"),
        ],
        [InlineKeyboardButton("‹ رجوع", callback_data="nav_dashboard")],
    ])

def build_journal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="nav_log")],
        [
            InlineKeyboardButton("📊 تقرير كامل", callback_data="nav_stats"),
            InlineKeyboardButton("📄 تصدير CSV",  callback_data="export_journal"),
        ],
        [InlineKeyboardButton("‹ رجوع", callback_data="nav_dashboard")],
    ])

# ══════════════════════════════════════════
#  10. SETTINGS
# ══════════════════════════════════════════

def build_settings_text() -> str:
    return (
        f"⚙️ *الإعدادات الرئيسية*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  اختر القسم الذي تريد تعديله"
    )

def build_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 التنبيهات",   callback_data="settings_alerts"),
            InlineKeyboardButton("🧠 نظام الذكاء", callback_data="settings_ai"),
        ],
        [
            InlineKeyboardButton("📊 نوع الإشارات", callback_data="settings_signals"),
            InlineKeyboardButton("💰 المبالغ",      callback_data="settings_amounts"),
        ],
        [
            InlineKeyboardButton("🔌 الاتصال", callback_data="settings_connection"),
            InlineKeyboardButton("🌐 اللغة",   callback_data="settings_lang"),
        ],
        [InlineKeyboardButton("⚠️ إعادة الضبط", callback_data="settings_reset")],
        [InlineKeyboardButton("‹ رجوع",          callback_data="nav_dashboard")],
    ])

def build_settings_alerts_text(payout: float, duration: int, live_payout_available: bool) -> str:
    payout_status = "✅" if live_payout_available else "⚠️ تقديري"
    return (
        f"📢 *التنبيهات*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  💰 العائد: `{payout:.0f}%` {payout_status}\n"
        f"  ⏱ المدة: `{duration}` ثانية"
    )

def build_settings_alerts_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 تحديث العوائد", callback_data="refresh_payout")],
        [InlineKeyboardButton("⏱ تغيير المدة",   callback_data="duration_menu")],
        [InlineKeyboardButton("⬅️ رجوع",         callback_data="nav_settings")],
    ])

def build_settings_ai_text(ai_enabled: bool, ml_available: bool) -> str:
    return (
        f"🤖 *نظام الذكاء*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🧠 AI: {'🟢 مفعّل' if ai_enabled else '🔴 معطل'}\n"
        f"  🤖 ML: {'🟢 مفعّل' if ml_available else '🔴 معطل'}"
    )

def build_settings_ai_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 حالة AI", callback_data="ai_status")],
        [InlineKeyboardButton("🤖 حالة ML", callback_data="ml_status")],
        [InlineKeyboardButton("⬅️ رجوع",   callback_data="nav_settings")],
    ])

def build_settings_signals_text(pair: str, min_score: int, paper_mode: bool) -> str:
    mode_s = "📋 تجريبي" if paper_mode else "💵 حقيقي"
    return (
        f"📊 *نوع الإشارات*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  📊 الزوج: `{pair}`\n"
        f"  🎯 الحد: `{min_score}/38` نقطة\n"
        f"  🎮 الوضع: {mode_s}"
    )

def build_settings_signals_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 تغيير الزوج", callback_data="pairs_menu")],
        [InlineKeyboardButton("🎯 تغيير الحد",  callback_data="score_menu")],
        [InlineKeyboardButton("⬅️ رجوع",       callback_data="nav_settings")],
    ])

def build_duration_keyboard(current_duration: int) -> InlineKeyboardMarkup:
    opts = [30, 60, 120, 300]
    row  = [
        InlineKeyboardButton(
            f"{'🟢 ' if v == current_duration else ''}{v}ث",
            callback_data=f"dur_{v}",
        )
        for v in opts
    ]
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("⬅️ رجوع", callback_data="nav_settings")],
    ])

def build_ai_status_text(
    enabled: bool,
    api_key_masked: str = "",
    total_calls: int = 0,
    total_cost: float = 0.0,
    cache_hit_rate: float = 0.0,
    key_hint: str = "",
) -> str:
    if enabled:
        return (
            f"🤖 *Gemini AI — مفعّل ✅*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  🔑 المفتاح: `{api_key_masked}`\n"
            f"  📞 استدعاءات: `{total_calls}`\n"
            f"  💸 التكلفة: `${total_cost:.4f}`\n"
            f"  💾 كاش: `{cache_hit_rate:.1f}%`"
        )
    return (
        f"🤖 *Gemini AI — غير مفعّل ❌*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"البوت يعمل بالخوارزميات فقط.\n"
        f"{key_hint}\n\n"
        f"*لتفعيل Gemini AI:*\n"
        f"1. اذهب إلى https://aistudio.google.com/apikey\n"
        f"2. أنشئ API Key\n"
        f"3. أضف في `.env`:\n"
        f"`ANTHROPIC_API_KEY=sk-ant-...`\n"
        f"4. أعد تشغيل البوت"
    )

def build_ml_status_text(
    available: bool,
    trees: int = 0,
    accuracy: float = 0.0,
    train_size: int = 0,
) -> str:
    if available:
        return (
            f"🤖 *ML — مفعّل ✅*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  🌲 الأشجار: `{trees}`\n"
            f"  📊 الدقة: `{accuracy * 100:.1f}%`\n"
            f"  📝 التدريب: `{train_size}` عينة"
        )
    return (
        f"🤖 *ML — معطل*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  ملف `trading_model.pkl` غير موجود"
    )

# ══════════════════════════════════════════
#  11. MISC
# ══════════════════════════════════════════

def build_pairs_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Live (حقيقية)", callback_data="pairs_live")],
        [InlineKeyboardButton("🔵 OTC",           callback_data="pairs_otc")],
        [InlineKeyboardButton("‹ رجوع",           callback_data="nav_dashboard")],
    ])

def build_result_keyboard(sid: str = "") -> InlineKeyboardMarkup:
    return build_signal_keyboard(is_running=True)

def build_help_text() -> str:
    return (
        f"❓ *تعليمات البوت*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🚀 بدء التداول ← يدوي: Trading ← Pairs ← Expiry\n"
        f"  🤖 تلقائي ← يختار ويبدأ مباشرة\n"
        f"  📊 إحصائيات الجلسة\n"
        f"  ⚙️ الإعدادات\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  /start — القائمة الرئيسية\n"
        f"  /signal — تحليل فوري\n"
        f"  /status — الحالة\n"
        f"  /stats — الإحصائيات\n"
        f"  /pairs — الأزواج\n"
        f"  /scan — مسح أفضل الأزواج\n"
        f"  /report — تقرير أسبوعي + أفضل الأزواج\n"
        f"  /accuracy — دقة النماذج\n"
        f"  /portfolio — المحفظة والتوزيع\n"
        f"  /optimize — تحسين أوزان النماذج\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  🔥 Confluence + AI + TV + Ensemble | 🧠 7 مصادر قرار"
    )

def build_error_text(msg: str) -> str:
    return f"❌ *خطأ:*\n{msg}"

# ══════════════════════════════════════════
#  12. ALIASES — للتوافق مع الكود القديم
# ══════════════════════════════════════════

def sep(title: str = "") -> str:
    return f"◆━ {title} ━━━━━━━◆" if title else "◆━━━━━━━━━━━━━━━━━━━━━━━━━━◆"

def build_main_text(*args, **kwargs) -> str:
    return build_dashboard_text(*args, **kwargs)

def build_main_keyboard(
    is_running: bool,
    paper_mode: bool,
    auto_mode: bool = False,
) -> InlineKeyboardMarkup:
    return build_dashboard_keyboard(is_running, paper_mode, auto_mode)
