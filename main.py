# main.py
from __future__ import annotations
import os, sys, time, socket, io, collections, threading
import telebot
from telebot import types
from telebot.apihelper import delete_webhook, ApiTelegramException

from pocket_map import PO_TO_FINNHUB, DEFAULT_SYMBOL
from data_fetcher import STATE, start_fetcher_in_thread, HAS_LIVE_KEY
from strategy import decide_from_ticks, CFG as STRAT_CFG
from auto_trader import AutoTrader
from learn import LEARNER

# ===== גרף =====
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

# ===== בחירות תפריט זמן וכו' =====
CANDLE_CHOICES = [("10s",10),("15s",15),("30s",30),("1m",60),("2m",120),("3m",180),("5m",300)]
TRADE_CHOICES  = [("10s",10),("30s",30),("1m",60),("2m",120),("3m",180),("5m",300)]
WINDOW_CHOICES = [16,22,26,30,45,60,90]
CHART_MODES    = ["CANDLE","LINE"]

# ===== מצב לנכס =====
class AssetConfig:
    def __init__(self):
        self.chart_mode: str = "CANDLE"
        self.candle_tf_sec: int = 60
        self.trade_expiry_sec: int = 60
        self.window_sec: int = 26
        self.daily_hits = collections.defaultdict(int)
        self.daily_miss = collections.defaultdict(int)

# ===== מצב גלובלי של הבוט =====
class BotState:
    def __init__(self):
        # מצב הנוכחי (נכס פעיל כרגע)
        self.po_asset: str = "EUR/USD"
        self.finnhub_symbol: str = PO_TO_FINNHUB.get(self.po_asset, DEFAULT_SYMBOL)

        # תצורה פר-נכס
        self.assets: dict[str,AssetConfig] = collections.defaultdict(AssetConfig)

        # session mode: PHONE / PC (נקבע ב-/start או /mode)
        self.session_mode: str = "PHONE"

        # אחרון סיגנל שנשלח
        self.last_signal_idx = None  # אינדקס ב-LEARNER של העסקה הפתוחה

APP = BotState()
AUTO = AutoTrader()

_fetcher_started = False

# ===== ENV בסיסיים לטלגרם =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_LOCK = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SINGLETON_PORT = int(os.getenv("SINGLETON_PORT", "47653"))
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)  # נשלח טקסט גולמי (בלי Markdown) כדי למנוע שגיאות 400

# ===== עזרי מערכת =====
def aggressive_reset():
    try: bot.remove_webhook()
    except Exception: pass
    try: delete_webhook(BOT_TOKEN, drop_pending_updates=True)
    except Exception: pass
    time.sleep(0.7)

_LOCK = None
def ensure_single_instance(port: int = SINGLETON_PORT):
    global _LOCK
    _LOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _LOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        _LOCK.bind(("127.0.0.1", port))
        _LOCK.listen(1)
    except OSError:
        print("Another instance is running. Exiting.")
        sys.exit(0)

def ensure_fetcher():
    global _fetcher_started
    if not _fetcher_started:
        start_fetcher_in_thread(lambda: APP.finnhub_symbol)
        _fetcher_started = True

def allowed(msg) -> bool:
    return (not CHAT_LOCK) or (str(msg.chat.id) == CHAT_LOCK)

def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())

# ===== אחזור/עדכון פר-נכס =====
def cur_cfg() -> AssetConfig:
    return APP.assets[APP.po_asset]

def refresh_symbol():
    APP.finnhub_symbol = PO_TO_FINNHUB.get(APP.po_asset, DEFAULT_SYMBOL)

def _fmt(x, fmt=".4g"):
    try: return format(float(x), fmt)
    except Exception: return "n/a"

def _price_decimals(po_asset: str) -> int:
    a = po_asset.upper()
    if "BTC" in a or "ETH" in a: return 2
    if "JPY" in a: return 3
    return 5

# ===== גרף להצגה =====
def make_price_png(ticks, window_sec: float, po_asset: str):
    now = time.time()
    win = [(ts, p) for (ts, p) in list(ticks) if now - ts <= window_sec]
    if len(win) < 6:
        win = list(ticks)[-6:]
    buf = io.BytesIO()
    fig = plt.figure(figsize=(6.6, 3.2))
    plt.clf()
    if not win:
        plt.title("No data yet")
        plt.xlabel("time [sec]")
        plt.ylabel("price")
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=140)
        plt.close(fig)
        return buf.getvalue()
    xs = [ts - win[0][0] for (ts, _) in win]
    ys = [p for (_, p) in win]
    last_price = ys[-1]
    plt.plot(xs, ys, linewidth=2.0, label="Price")
    plt.axhline(last_price, linestyle="--", linewidth=1.2, label="Last Price")
    plt.xlabel("time [sec]")
    dec = _price_decimals(po_asset)
    plt.gca().yaxis.set_major_formatter(FormatStrFormatter(f"%.{dec}f"))
    plt.ylabel("price")
    plt.grid(True, linestyle="--", alpha=0.35)
    plt.legend(loc="best", frameon=True)
    plt.title("Last ~window price view")
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    return buf.getvalue()

# ===== סינכרון הגדרות בין TF/Expiry/Window =====
def _nearest_choice(val: int, choices: list[int]) -> int:
    return min(choices, key=lambda c: abs(c - val))

def sync_from_tf_trade():
    cfg = cur_cfg()
    tx = cfg.trade_expiry_sec
    if cfg.chart_mode == "CANDLE":
        tf = cfg.candle_tf_sec
        wnd = max(3*tf, int(0.8*tx))
    else:
        wnd = int(0.9*tx)
    wnd = max(16, min(wnd, 90))
    cfg.window_sec = wnd
    STRAT_CFG["WINDOW_SEC"] = float(wnd)
    STRAT_CFG["EXPIRY"] = f"{tx}s" if tx < 60 else f"{int(tx/60)}m"

def sync_from_window():
    cfg = cur_cfg()
    w = cfg.window_sec
    if cfg.chart_mode == "CANDLE":
        target_tf = max(10, int(round(w/3)))
        tf_allowed = [sec for _, sec in CANDLE_CHOICES]
        cfg.candle_tf_sec = _nearest_choice(target_tf, tf_allowed)
        target_tx = int(round(w*1.25))
    else:
        target_tx = int(round(w*1.10))
    tx_allowed = [sec for _, sec in TRADE_CHOICES]
    cfg.trade_expiry_sec = _nearest_choice(target_tx, tx_allowed)
    STRAT_CFG["WINDOW_SEC"] = float(cfg.window_sec)
    STRAT_CFG["EXPIRY"] = f"{cfg.trade_expiry_sec}s" if cfg.trade_expiry_sec < 60 else f"{int(cfg.trade_expiry_sec/60)}m"

def recommend_from_expiry(expiry_sec: int):
    cfg = cur_cfg()
    if cfg.chart_mode == "LINE":
        wnd = max(16, min(int(0.9*expiry_sec), 90))
        return None, wnd
    tf_allowed = [sec for _, sec in CANDLE_CHOICES]
    tf_guess = max(10, int(round(expiry_sec/3)))
    tf = _nearest_choice(tf_guess, tf_allowed)
    wnd = max(3*tf, int(0.8*expiry_sec))
    wnd = max(16, min(wnd, 90))
    return f"{tf}s", wnd

# ===== דירוג איכות ומרכיב multi-timeframe agreement =====
def quality_label(conf: int, align_bonus: float) -> str:
    if conf >= 75 or align_bonus >= 0.2:
        return "🟩 Strong"
    if conf >= 65:
        return "🟨 Medium"
    return "🟥 Weak"

def multi_timeframe_agree(dbg: dict) -> bool:
    # dbg יכול להכיל side_short, side_mid, side_long
    s_short = dbg.get("side_short")
    s_mid   = dbg.get("side_mid")
    s_long  = dbg.get("side_long")
    if not s_short or not s_mid or not s_long:
        return False
    return (s_short == s_mid == s_long) and s_short in ("UP","DOWN")

# ===== מקלדות דינמיות לפי מצב =====
def phone_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton("📊 נכס"))
    kb.add(types.KeyboardButton("📈 מצב תרשים"), types.KeyboardButton("⏳ זמן עסקה"))
    kb.add(types.KeyboardButton("🕒 זמן נר"), types.KeyboardButton("🪟 חלון ניתוח"))
    kb.add(types.KeyboardButton("🧠 סיגנל"), types.KeyboardButton("🖼️ ויזואל"))
    kb.add(types.KeyboardButton("🛰️ סטטוס"), types.KeyboardButton("📈 ביצועים"))
    kb.add(types.KeyboardButton("✅ פגיעה"), types.KeyboardButton("❌ החטאה"))
    kb.add(types.KeyboardButton("📘 הוראות"))
    return kb

def pc_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton("📊 נכס"))
    kb.add(types.KeyboardButton("📈 מצב תרשים"), types.KeyboardButton("⏳ זמן עסקה"))
    kb.add(types.KeyboardButton("🕒 זמן נר"), types.KeyboardButton("🪟 חלון ניתוח"))
    kb.add(types.KeyboardButton("🧠 סיגנל"), types.KeyboardButton("🖼️ ויזואל"))
    kb.add(types.KeyboardButton("🛰️ סטטוס"), types.KeyboardButton("📈 ביצועים"))
    kb.add(types.KeyboardButton("🤖 מסחר אוטומטי"), types.KeyboardButton("⚙️ Auto-Settings"))
    kb.add(types.KeyboardButton("✅ פגיעה"), types.KeyboardButton("❌ החטאה"))
    kb.add(types.KeyboardButton("📘 הוראות"))
    return kb

def current_menu():
    return pc_menu() if APP.session_mode == "PC" else phone_menu()

def asset_inline_keyboard(page: int = 0, page_size: int = 6):
    keys = list(PO_TO_FINNHUB.keys())
    start = page * page_size
    chunk = keys[start:start + page_size]
    markup = types.InlineKeyboardMarkup()
    for k in chunk:
        markup.add(types.InlineKeyboardButton(f"🎯 {k}", callback_data=f"asset::{k}::{page}"))
    nav=[]
    if start>0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"asset_nav::{page-1}"))
    if start+page_size < len(keys):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"asset_nav::{page+1}"))
    if nav:
        markup.row(*nav)
    return markup

def chartmode_keyboard():
    m = types.InlineKeyboardMarkup()
    m.row(
        types.InlineKeyboardButton("נרות (Candles)", callback_data="chart::CANDLE"),
        types.InlineKeyboardButton("קו (Line)", callback_data="chart::LINE"),
    )
    return m

def choices_inline_keyboard(kind: str):
    if kind == "window":
        markup = types.InlineKeyboardMarkup()
        for w in WINDOW_CHOICES:
            markup.add(types.InlineKeyboardButton(f"{w}s", callback_data=f"set_window::{w}"))
        markup.add(types.InlineKeyboardButton("חלון ידני…", callback_data="window_manual"))
        markup.add(types.InlineKeyboardButton("חזרה", callback_data="back_main"))
        return markup

    markup = types.InlineKeyboardMarkup()
    pairs = TRADE_CHOICES if kind == "trade" else CANDLE_CHOICES
    row=[]
    for label, sec in pairs:
        row.append(types.InlineKeyboardButton(label, callback_data=f"set_{kind}::{sec}"))
        if len(row)==4:
            markup.row(*row); row=[]
    if row:
        markup.row(*row)
    markup.add(types.InlineKeyboardButton("חזרה", callback_data="back_main"))
    return markup

def manual_window_keyboard():
    markup = types.InlineKeyboardMarkup()
    for w in (10,15,20,25,35,40,50,70,80,100,110):
        markup.add(types.InlineKeyboardButton(f"{w}s", callback_data=f"set_window::{w}"))
    markup.add(types.InlineKeyboardButton("חזרה", callback_data="back_main"))
    return markup

# ===== הודעות עזר =====
def print_all(chat_id: int, header: str):
    cfg = cur_cfg()
    lines = [
        header,
        f"Session Mode: {APP.session_mode}",
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Source: {'LIVE (Finnhub)' if HAS_LIVE_KEY else 'MISSING_API_KEY'}",
        f"Chart Mode: {cfg.chart_mode}",
        f"TF (Chart): { (str(cfg.candle_tf_sec)+'s') if cfg.chart_mode=='CANDLE' else 'N/A (Line)'}",
        f"Trade Expiry: {cfg.trade_expiry_sec}s",
        f"Analysis Window: {cfg.window_sec}s",
    ]
    bot.send_message(chat_id, "\n".join(lines), reply_markup=current_menu())

def send_instructions(chat_id: int):
    cfg = cur_cfg()
    if cfg.chart_mode == "CANDLE":
        txt = (
            "📘 הוראות PO:\n"
            f"1) פתח {APP.po_asset}\n"
            f"2) Chart Mode: Candles ; TF = {cfg.candle_tf_sec}s\n"
            f"3) Trade Expiry = {cfg.trade_expiry_sec}s\n"
            f"4) הבוט מנתח חלון = {cfg.window_sec}s\n"
            "טיפ: איכות Strong 🟩 עדיפה לכניסה"
        )
    else:
        txt = (
            "📘 הוראות PO:\n"
            f"1) פתח {APP.po_asset}\n"
            "2) Chart Mode: Line (אין TF)\n"
            f"3) Trade Expiry = {cfg.trade_expiry_sec}s\n"
            f"4) חלון ניתוח = {cfg.window_sec}s\n"
            "טיפ: חפש Strong 🟩"
        )
    bot.send_message(chat_id, txt, reply_markup=current_menu())

# ===== התאמת thresholds מהלימוד החי =====
def adapt_thresholds_from_learning():
    # משתמש ב-LEARNER כדי לכוון קצת את AUTO thresholds
    base_enter = AUTO.state.threshold_enter
    base_aggr  = AUTO.state.threshold_aggr
    new_enter, new_aggr = LEARNER.dynamic_thresholds(base_enter, base_aggr)
    AUTO.set_threshold_enter(new_enter)
    AUTO.set_threshold_aggr(new_aggr)

# ===== פונקציה שמפיקה סיגנל מורחב (כולל multi-timeframe וכו') =====
def get_decision():
    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    # side in ("UP","DOWN","WAIT")
    q = quality_label(conf, float(dbg.get("align_bonus",0.0)))
    agree3 = multi_timeframe_agree(dbg)

    # strong_ok = האם מותר כניסה גם בסף האגרסיבי במידה והביטחון בינוני
    strong_ok = (q == "🟩 Strong" and agree3)

    info = {
        "side": side,
        "conf": conf,
        "quality": q,
        "agree3": agree3,
        "rsi": dbg.get("rsi"),
        "vol": dbg.get("vol"),
        "ema_spread": dbg.get("ema_spread"),
        "trend_slope": dbg.get("trend_slope"),
        "persist": dbg.get("persist"),
        "tick_imb": dbg.get("tick_imb"),
        "align_bonus": dbg.get("align_bonus"),
        "strong_ok": strong_ok,
    }
    return info

# ===== HANDLERS =====
@bot.message_handler(commands=["start"])
def on_start(msg):
    if not allowed(msg): return
    ensure_fetcher(); aggressive_reset()
    # נשאל אם פלאפון או מחשב
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📱 פלאפון", callback_data="mode::PHONE"))
    kb.add(types.InlineKeyboardButton("💻 מחשב", callback_data="mode::PC"))
    bot.send_message(msg.chat.id,
        "איפה אתה עכשיו? כך אתאים לך תפריט ויכולות:",
        reply_markup=kb
    )

@bot.message_handler(commands=["mode"])
def on_mode(msg):
    if not allowed(msg): return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📱 פלאפון", callback_data="mode::PHONE"))
    kb.add(types.InlineKeyboardButton("💻 מחשב", callback_data="mode::PC"))
    bot.send_message(msg.chat.id,
        "בחר מצב עבודה:",
        reply_markup=kb
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("mode::"))
def on_mode_pick(c):
    if not allowed(c.message): return
    m = c.data.split("::")[1]
    APP.session_mode = "PC" if m=="PC" else "PHONE"

    # עדכון fetcher אם צריך סמלים
    refresh_symbol()
    # סנכרון ראשוני של STRAT_CFG לפי הנכס/הגדרות
    sync_from_tf_trade()

    bot.answer_callback_query(c.id, text=f"Mode={APP.session_mode}")
    print_all(c.message.chat.id, "מצב עודכן")
    send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📘 הוראות")
def on_instructions(msg):
    send_instructions(msg.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📊 נכס")
def on_asset(msg):
    bot.send_message(msg.chat.id,
        f"נכס נוכחי: {APP.po_asset}\nבחר נכס:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.send_message(msg.chat.id, "רשימת נכסים:", reply_markup=asset_inline_keyboard(page=0))

@bot.callback_query_handler(func=lambda c: c.data.startswith("asset_nav::"))
def on_asset_nav(c):
    if not allowed(c.message): return
    page = int(c.data.split("::")[1])
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text="רשימת נכסים:", reply_markup=asset_inline_keyboard(page=page))

@bot.callback_query_handler(func=lambda c: c.data.startswith("asset::"))
def on_asset_pick(c):
    if not allowed(c.message): return
    _, po_name, page = c.data.split("::")
    APP.po_asset = po_name
    refresh_symbol()
    # לסנכרן STRAT_CFG בהתאם לנכס הזה
    sync_from_tf_trade()
    bot.answer_callback_query(c.id, text=f"נבחר: {po_name}")
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text=f"נכס נבחר: {po_name} → {APP.finnhub_symbol}",
                          reply_markup=asset_inline_keyboard(page=int(page)))
    print_all(c.message.chat.id, "הנכס עודכן")
    send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📈 מצב תרשים")
def on_chartmode(msg):
    bot.send_message(msg.chat.id, "בחר מצב תרשים:", reply_markup=chartmode_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("chart::"))
def on_chartmode_pick(c):
    cfg = cur_cfg()
    mode = c.data.split("::")[1]
    cfg.chart_mode = mode if mode in CHART_MODES else "CANDLE"
    sync_from_tf_trade()
    bot.answer_callback_query(c.id, text=f"Chart={cfg.chart_mode}")
    print_all(c.message.chat.id, "מצב התרשים עודכן")
    send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🕒 זמן נר")
def on_candle(msg):
    cfg = cur_cfg()
    if cfg.chart_mode == "LINE":
        bot.send_message(msg.chat.id,
            "במצב Line אין זמן נר (TF). בחר ⏳ זמן עסקה או 🪟 חלון ניתוח.",
            reply_markup=current_menu())
        return
    bot.send_message(msg.chat.id, "בחר זמן נר:", reply_markup=choices_inline_keyboard("candle"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_candle::"))
def on_set_candle(c):
    cfg = cur_cfg()
    if cfg.chart_mode == "LINE":
        bot.answer_callback_query(c.id, text="ב-Line אין TF")
        return
    sec = int(c.data.split("::")[1])
    cfg.candle_tf_sec = sec
    sync_from_tf_trade()
    bot.answer_callback_query(c.id, text=f"TF={sec}s")
    print_all(c.message.chat.id, "זמן הנר עודכן")
    send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⏳ זמן עסקה")
def on_trade(msg):
    bot.send_message(msg.chat.id, "בחר זמן עסקה:", reply_markup=choices_inline_keyboard("trade"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_trade::"))
def on_set_trade(c):
    cfg = cur_cfg()
    sec = int(c.data.split("::")[1])
    cfg.trade_expiry_sec = sec
    rec_tf, rec_w = recommend_from_expiry(sec)
    cfg.window_sec = rec_w
    if cfg.chart_mode == "CANDLE" and rec_tf is not None:
        cfg.candle_tf_sec = int(rec_tf[:-1])  # "60s" -> 60
    STRAT_CFG["WINDOW_SEC"] = float(rec_w)
    STRAT_CFG["EXPIRY"] = f"{sec}s" if sec < 60 else f"{int(sec/60)}m"
    bot.answer_callback_query(c.id, text=f"Expiry={sec}s")
    if cfg.chart_mode == "CANDLE":
        bot.send_message(c.message.chat.id,
            f"התאמה אוטומטית:\nTF מומלץ: {cfg.candle_tf_sec}s\nחלון ניתוח: {rec_w}s",
            reply_markup=current_menu())
    else:
        bot.send_message(c.message.chat.id,
            f"התאמה אוטומטית (Line):\nחלון ניתוח: {rec_w}s (אין TF)",
            reply_markup=current_menu())
    print_all(c.message.chat.id, "זמן העסקה עודכן")
    send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🪟 חלון ניתוח")
def on_window(msg):
    bot.send_message(msg.chat.id,
        "בחר חלון (או 'חלון ידני…'):",
        reply_markup=choices_inline_keyboard("window"))

@bot.callback_query_handler(func=lambda c: c.data == "window_manual")
def on_window_manual(c):
    bot.answer_callback_query(c.id)
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text="בחר חלון ידני:", reply_markup=manual_window_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_window::"))
def on_set_window(c):
    cfg = cur_cfg()
    sec = int(c.data.split("::")[1])
    cfg.window_sec = max(10, min(sec, 120))
    sync_from_window()
    bot.answer_callback_query(c.id, text=f"Window={cfg.window_sec}s")
    print_all(c.message.chat.id, "חלון הניתוח עודכן")
    send_instructions(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def on_back_main(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "תפריט ראשי:", reply_markup=current_menu())

# ===== סיגנל / ויזואל / סטטוס / ביצועים =====
@bot.message_handler(func=lambda m: allowed(m) and m.text == "🧠 סיגנל")
def on_signal(msg):
    cfg = cur_cfg()
    info = get_decision()

    # נסתנכרן ל-LEARNER: פותחים "עסקה במעקב"
    if info["side"] in ("UP","DOWN"):
        APP.last_signal_idx = LEARNER.new_sample(
            asset=APP.po_asset,
            side=info["side"],
            conf=info["conf"],
            quality=info["quality"],
            agree3=info["agree3"],
            rsi=info["rsi"] if info["rsi"] is not None else -1.0,
            ema_spread=info["ema_spread"] if info["ema_spread"] is not None else 0.0,
            persist=info["persist"] if info["persist"] is not None else 0.0,
            tick_imb=info["tick_imb"] if info["tick_imb"] is not None else 0.0,
            align_bonus=info["align_bonus"] if info["align_bonus"] is not None else 0.0,
        )
    else:
        APP.last_signal_idx = None

    # ננסה לסחור אוטומטית אם אנחנו במחשב
    auto_line = ""
    if APP.session_mode == "PC":
        traded = False
        if info["side"] in ("UP","DOWN"):
            # עדכון thresholds דינמי מהלמידה לפני ההחלטה
            adapt_thresholds_from_learning()
            traded = AUTO.place_if_allowed(
                side=info["side"],
                conf=info["conf"],
                strong_ok=info["strong_ok"]
            )
        if traded:
            auto_line = "💻 AutoTrade: נכנס " + ("↑" if info["side"]=="UP" else "↓")
        else:
            auto_line = f"💻 AutoTrade: {AUTO.state.last_action or 'לא נכנס'}"

    arrow = "🔼" if info["side"] == "UP" else "🔽" if info["side"] == "DOWN" else "⏳"
    lines = [
        "סיגנל",
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Chart Mode: {cfg.chart_mode}",
        f"TF: {cfg.candle_tf_sec}s" if cfg.chart_mode=="CANDLE" else "TF: N/A (Line)",
        f"Expiry: {cfg.trade_expiry_sec}s",
        f"Window: {cfg.window_sec}s",
        f"Decision: {info['side']} {arrow}",
        f"Confidence: {info['conf']}%",
        f"Quality: {info['quality']}",
        f"Agree3TF: {'YES' if info['agree3'] else 'NO'}",
        f"RSI: {_fmt(info['rsi'],'.1f')} | Vol: {_fmt(info['vol'],'.2e')}",
        f"ema_spread: {_fmt(info['ema_spread'])} | slope: {_fmt(info['trend_slope'])}",
        f"persist: {_fmt(info['persist'],'.2f')} | tick_imb: {_fmt(info['tick_imb'],'.2f')} | align_bonus: {_fmt(info['align_bonus'],'.2f')}",
    ]
    if APP.session_mode == "PC":
        lines.append(auto_line)

    png = make_price_png(STATE["ticks"], cfg.window_sec, APP.po_asset)
    bot.send_photo(msg.chat.id, png, caption="\n".join(lines), reply_markup=current_menu())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🖼️ ויזואל")
def on_visual(msg):
    cfg = cur_cfg()
    png = make_price_png(STATE["ticks"], cfg.window_sec, APP.po_asset)
    cap = "גרף מחיר בחלון האחרון (X=sec, Y=price). הקו המקווקו הוא המחיר הנוכחי."
    bot.send_photo(msg.chat.id, png, caption=cap, reply_markup=current_menu())

def status_header() -> list[str]:
    src = 'LIVE (Finnhub)' if HAS_LIVE_KEY else 'MISSING_API_KEY'
    return [
        f"Source: {src}",
        f"WS Online: {'Yes' if STATE['ws_online'] else 'No'}",
        f"Reconnects: {STATE['reconnects']}",
        f"Msg recv: {STATE['msg_count']}",
    ]

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🛰️ סטטוס")
def on_status(msg):
    cfg = cur_cfg()
    now = time.time()
    ticks = list(STATE["ticks"])
    n_total = len(ticks)
    n_win = len([1 for (ts, _) in ticks if now - ts <= cfg.window_sec])
    age_ms = int((now - STATE["last_recv_ts"]) * 1000) if STATE["last_recv_ts"] else None

    info = get_decision()
    learn_summary = LEARNER.summarize()

    lines = ["סטטוס"]
    lines += status_header()
    lines += [
        f"Last tick age: {age_ms if age_ms is not None else 'n/a'} ms",
        f"Session Mode: {APP.session_mode}",
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Chart Mode: {cfg.chart_mode}",
        f"TF (Chart): { (str(cfg.candle_tf_sec)+'s') if cfg.chart_mode=='CANDLE' else 'N/A (Line)'}",
        f"Trade Expiry: {cfg.trade_expiry_sec}s",
        f"Analysis Window: {cfg.window_sec}s",
        f"Window ticks: {n_win}/{n_total}",
        f"Signal: {info['side']}",
        f"Confidence: {info['conf']}%",
        f"Quality: {info['quality']}",
        f"Agree3TF: {'YES' if info['agree3'] else 'NO'}",
        f"RSI: {_fmt(info['rsi'],'.1f')} | Vol: {_fmt(info['vol'],'.2e')}",
        f"EMA spread: {_fmt(info['ema_spread'])}",
        f"Trend slope: {_fmt(info['trend_slope'])}",
        f"Persistence: {_fmt(info['persist'],'.2f')}",
        f"Tick imbalance: {_fmt(info['tick_imb'],'.2f')}",
        f"Align bonus: {_fmt(info['align_bonus'],'.2f')}",
        "",
        "למידה חיה",
        f"Strong win%: {learn_summary['Strong win%']}",
        f"Medium win%: {learn_summary['Medium win%']}",
        f"Weak win%: {learn_summary['Weak win%']}",
        f"Agree3 win%: {learn_summary['Agree3 win%']}",
    ]

    if APP.session_mode == "PC":
        lines += [
            "",
            "Auto-Trading",
        ]
        lines += AUTO.status_lines()

    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=current_menu())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📈 ביצועים")
def on_performance(msg):
    cfg = cur_cfg()
    day = _today_key()
    hits = cfg.daily_hits[day]
    miss = cfg.daily_miss[day]
    total = hits + miss
    wr = (100.0*hits/total) if total>0 else 0.0
    lines = [
        "ביצועים (היום לנכס הזה)",
        f"Hits (✅): {hits}",
        f"Misses (❌): {miss}",
        f"Total: {total}",
        f"Win-Rate: {_fmt(wr,'.1f')}%",
        "הערה: ה-Win-Rate כאן הוא הדיווח הידני שלך.",
    ]
    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=current_menu())

# ===== דיווח הצלחה / כישלון =====
@bot.message_handler(func=lambda m: allowed(m) and m.text in ["✅ פגיעה","❌ החטאה"])
def on_result(msg):
    cfg = cur_cfg()
    day = _today_key()
    success = (msg.text == "✅ פגיעה")
    if success:
        cfg.daily_hits[day] += 1
    else:
        cfg.daily_miss[day] += 1

    # נשמור את הצלחה/כישלון גם בלמידה
    idx = APP.last_signal_idx
    if idx is not None:
        LEARNER.mark_result(idx, success)
        APP.last_signal_idx = None  # "סגרנו" את העסקה הזו

    bot.send_message(
        msg.chat.id,
        "נרשם. ממשיכים.",
        reply_markup=current_menu()
    )

# ===== מסחר אוטומטי (PC בלבד) =====
@bot.message_handler(func=lambda m: allowed(m) and m.text == "🤖 מסחר אוטומטי")
def on_auto_toggle(msg):
    if APP.session_mode != "PC":
        bot.send_message(msg.chat.id, "זמין רק במצב מחשב 💻.", reply_markup=current_menu())
        return
    if AUTO.state.enabled:
        AUTO.disable()
        bot.send_message(msg.chat.id, "Auto-Trading: OFF", reply_markup=current_menu())
    else:
        AUTO.enable()
        bot.send_message(msg.chat.id, "Auto-Trading: ON", reply_markup=current_menu())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⚙️ Auto-Settings")
def on_auto_settings(msg):
    if APP.session_mode != "PC":
        bot.send_message(msg.chat.id, "זמין רק במצב מחשב 💻.", reply_markup=current_menu())
        return

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("Enter Thr −5", callback_data="auto::enter:-5"),
        types.InlineKeyboardButton("Enter Thr +5", callback_data="auto::enter:+5"),
    )
    kb.row(
        types.InlineKeyboardButton("Aggr Thr −5", callback_data="auto::aggr:-5"),
        types.InlineKeyboardButton("Aggr Thr +5", callback_data="auto::aggr:+5"),
    )
    kb.row(
        types.InlineKeyboardButton("Interval −5s", callback_data="auto::ival:-5"),
        types.InlineKeyboardButton("Interval +5s", callback_data="auto::ival:+5"),
    )
    kb.add(types.InlineKeyboardButton("סטטוס אוטו", callback_data="auto::status"))
    bot.send_message(msg.chat.id, "הגדרות אוטומציה:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("auto::"))
def on_auto_cb(c):
    if not allowed(c.message): return
    if APP.session_mode != "PC":
        bot.answer_callback_query(c.id, text="מצב מחשב בלבד")
        return

    _, kind, val = c.data.split("::")
    delta = int(val) if val not in ("status",) else 0

    if kind == "enter":
        AUTO.set_threshold_enter(AUTO.state.threshold_enter + delta)
        bot.answer_callback_query(c.id, text=f"Enter Thr ≥ {AUTO.state.threshold_enter}")
    elif kind == "aggr":
        AUTO.set_threshold_aggr(AUTO.state.threshold_aggr + delta)
        bot.answer_callback_query(c.id, text=f"Aggr Thr ≥ {AUTO.state.threshold_aggr}")
    elif kind == "ival":
        AUTO.set_min_interval(AUTO.state.min_interval_sec + delta)
        bot.answer_callback_query(c.id, text=f"Interval = {AUTO.state.min_interval_sec}s")
    elif kind == "status":
        bot.answer_callback_query(c.id, text="Auto status")

    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text="\n".join(AUTO.status_lines()),
        reply_markup=None
    )

# ===== לולאת החלטה ברקע למסחר אוטומטי (PC בלבד) =====
def auto_loop():
    while True:
        try:
            if APP.session_mode == "PC" and AUTO.state.enabled:
                info = get_decision()
                if info["side"] in ("UP","DOWN"):
                    adapt_thresholds_from_learning()
                    AUTO.place_if_allowed(
                        side=info["side"],
                        conf=info["conf"],
                        strong_ok=info["strong_ok"]
                    )
            time.sleep(2.0)
        except Exception as e:
            print("[AUTO LOOP] exception:", e)
            time.sleep(2.0)

# ===== PANIC & Runner =====
@bot.message_handler(commands=["panic"])
def on_panic(msg):
    if not allowed(msg): return
    try: bot.remove_webhook()
    except Exception: pass
    try: delete_webhook(BOT_TOKEN, drop_pending_updates=True)
    except Exception: pass
    bot.send_message(msg.chat.id, "PANIC. יוצא.")
    sys.exit(0)

def run_forever():
    while True:
        try:
            aggressive_reset()
            print("Bot started polling…")
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except ApiTelegramException as e:
            code = getattr(e, "result_json", {}).get("error_code", None) if hasattr(e, "result_json") else None
            if code == 409:
                print("[409] cleaning webhook & retry")
                aggressive_reset()
                continue
            print("ApiTelegramException:", e)
            time.sleep(2)
        except Exception as e:
            print("polling exception:", e)
            time.sleep(2)

def main():
    ensure_single_instance()
    ensure_fetcher()
    sync_from_tf_trade()  # איניט ראשון לנכס ברירת המחדל
    t = threading.Thread(target=auto_loop, daemon=True)
    t.start()
    run_forever()

if __name__ == "__main__":
    main()
