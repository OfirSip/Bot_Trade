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

# ===== גרף =====
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

# ===== בחירות =====
CANDLE_CHOICES = [("10s",10),("15s",15),("30s",30),("1m",60),("2m",120),("3m",180),("5m",300)]
TRADE_CHOICES  = [("10s",10),("30s",30),("1m",60),("2m",120),("3m",180),("5m",300)]
WINDOW_CHOICES = [16,22,26,30,45,60,90]
CHART_MODES    = ["CANDLE","LINE"]

# ===== מצב אפליקציה =====
class BotState:
    def __init__(self):
        self.po_asset: str = "EUR/USD"
        self.finnhub_symbol: str = PO_TO_FINNHUB.get(self.po_asset, DEFAULT_SYMBOL)
        self.chart_mode: str = "CANDLE"   # "CANDLE" / "LINE"
        self.candle_tf_sec: int = 60      # ב-LINE מוצג כ-N/A
        self.trade_expiry_sec: int = 60
        self.window_sec: int = 26
        # ביצועים יומיים
        self.daily_hits = collections.defaultdict(int)
        self.daily_miss = collections.defaultdict(int)
        self.last_signal = None

APP = BotState()
AUTO = AutoTrader()
_fetcher_started = False

# ===== ENV בסיסיים לטלגרם =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_LOCK = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SINGLETON_PORT = int(os.getenv("SINGLETON_PORT", "47653"))
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)  # parse_mode=None כדי למנוע שגיאות Markdown

# ===== Anti-409 & single-instance =====
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

# ===== עזרי תצוגה =====
def _fmt(x, fmt=".4g"):
    try: return format(float(x), fmt)
    except Exception: return "n/a"

def _price_decimals(po_asset: str) -> int:
    a = po_asset.upper()
    if "BTC" in a or "ETH" in a: return 2
    if "JPY" in a: return 3
    return 5

def make_explained_price_png(ticks, window_sec: float, po_asset: str):
    now = time.time()
    win = [(ts, p) for (ts, p) in list(ticks) if now - ts <= window_sec]
    if len(win) < 6: win = list(ticks)[-6:]
    buf = io.BytesIO()
    fig = plt.figure(figsize=(6.6, 3.2))
    plt.clf()
    if not win:
        plt.title("No data yet"); plt.xlabel("time [sec]"); plt.ylabel("price")
        fig.tight_layout(); fig.savefig(buf, format="png", dpi=140); plt.close(fig)
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
    fig.tight_layout(); fig.savefig(buf, format="png", dpi=140); plt.close(fig)
    return buf.getvalue()

# ===== סנכרון פרמטרים דו־כיווני =====
def _nearest_choice(val: int, choices: list[int]) -> int:
    return min(choices, key=lambda c: abs(c - val))

def _sync_from_tf_trade():
    tx = APP.trade_expiry_sec
    if APP.chart_mode == "CANDLE":
        tf = APP.candle_tf_sec
        wnd = max(3*tf, int(0.8*tx))
    else:  # LINE (אין TF)
        wnd = int(0.9*tx)
    wnd = max(16, min(wnd, 90))
    APP.window_sec = wnd
    STRAT_CFG["WINDOW_SEC"] = float(wnd)
    STRAT_CFG["EXPIRY"] = f"{tx}s" if tx < 60 else f"{int(tx/60)}m"

def _sync_from_window():
    w = APP.window_sec
    if APP.chart_mode == "CANDLE":
        target_tf = max(10, int(round(w/3)))
        tf_allowed = [sec for _, sec in CANDLE_CHOICES]
        APP.candle_tf_sec = _nearest_choice(target_tf, tf_allowed)
        target_tx = int(round(w*1.25))
    else:
        target_tx = int(round(w*1.10))
    tx_allowed = [sec for _, sec in TRADE_CHOICES]
    APP.trade_expiry_sec = _nearest_choice(target_tx, tx_allowed)
    STRAT_CFG["WINDOW_SEC"] = float(APP.window_sec)
    STRAT_CFG["EXPIRY"] = f"{APP.trade_expiry_sec}s" if APP.trade_expiry_sec < 60 else f"{int(APP.trade_expiry_sec/60)}m"

def _recommend_from_expiry(expiry_sec: int) -> tuple[str | None, int]:
    if APP.chart_mode == "LINE":
        wnd = max(16, min(int(0.9*expiry_sec), 90))
        return None, wnd
    tf_allowed = [sec for _, sec in CANDLE_CHOICES]
    tf_guess = max(10, int(round(expiry_sec/3)))
    tf = _nearest_choice(tf_guess, tf_allowed)
    wnd = max(3*tf, int(0.8*expiry_sec))
    wnd = max(16, min(wnd, 90))
    return f"{tf}s", wnd

def _quality_label(conf: int, align_bonus: float) -> str:
    if conf >= 75 or align_bonus >= 0.2: return "🟩 Strong"
    if conf >= 65: return "🟨 Medium"
    return "🟥 Weak"

def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())

# ===== מקלדות =====
def main_menu_markup():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton("📊 נכס"))
    kb.add(types.KeyboardButton("📈 מצב תרשים"), types.KeyboardButton("⏳ זמן עסקה"))
    kb.add(types.KeyboardButton("🕒 זמן נר"), types.KeyboardButton("🪟 חלון ניתוח"))
    kb.add(types.KeyboardButton("📘 הוראות"), types.KeyboardButton("📈 ביצועים"))
    kb.add(types.KeyboardButton("🛰️ סטטוס"), types.KeyboardButton("🖼️ ויזואל"))
    kb.add(types.KeyboardButton("🧠 סיגנל"))
    kb.add(types.KeyboardButton("🤖 מסחר אוטומטי"), types.KeyboardButton("⚙️ Auto-Settings"))
    return kb

def asset_inline_keyboard(page: int = 0, page_size: int = 6):
    keys = list(PO_TO_FINNHUB.keys())
    start = page * page_size
    chunk = keys[start:start + page_size]
    markup = types.InlineKeyboardMarkup()
    for k in chunk:
        markup.add(types.InlineKeyboardButton(f"🎯 {k}", callback_data=f"asset::{k}::{page}"))
    nav = []
    if start > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"asset_nav::{page-1}"))
    if start + page_size < len(keys): nav.append(types.InlineKeyboardButton("➡️", callback_data=f"asset_nav::{page+1}"))
    if nav: markup.row(*nav)
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
        if len(row)==4: markup.row(*row); row=[]
    if row: markup.row(*row)
    markup.add(types.InlineKeyboardButton("חזרה", callback_data="back_main"))
    return markup

def manual_window_keyboard():
    markup = types.InlineKeyboardMarkup()
    for w in (10, 15, 20, 25, 35, 40, 50, 70, 80, 100, 110):
        markup.add(types.InlineKeyboardButton(f"{w}s", callback_data=f"set_window::{w}"))
    markup.add(types.InlineKeyboardButton("חזרה", callback_data="back_main"))
    return markup

def signal_feedback_keyboard():
    m = types.InlineKeyboardMarkup()
    m.row(
        types.InlineKeyboardButton("✅ פגיעה", callback_data="sig::hit"),
        types.InlineKeyboardButton("❌ החטאה", callback_data="sig::miss"),
    )
    return m

# ===== הודעות עזר =====
def _print_all(chat_id: int, header: str):
    lines = [
        header,
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Source: {'LIVE (Finnhub)' if HAS_LIVE_KEY else 'MISSING_API_KEY'}",
        f"Chart Mode: {APP.chart_mode}",
    ]
    if APP.chart_mode == "CANDLE":
        lines.append(f"TF (Chart): {APP.candle_tf_sec}s")
    else:
        lines.append("TF (Chart): N/A (Line)")
    lines += [
        f"Trade Expiry: {APP.trade_expiry_sec}s",
        f"Analysis Window: {APP.window_sec}s",
    ]
    bot.send_message(chat_id, "\n".join(lines), reply_markup=main_menu_markup())

def _send_instructions(chat_id: int):
    if APP.chart_mode == "CANDLE":
        txt = (
            "📘 הוראות PO:\n"
            f"1) פתח {APP.po_asset}.\n"
            f"2) Chart Mode: Candles ; TF = {APP.candle_tf_sec}s.\n"
            f"3) Trade Expiry = {APP.trade_expiry_sec}s.\n"
            f"4) הבוט מנתח חלון = {APP.window_sec}s.\n"
            "טיפ: איכות 🟩 Strong עדיפה."
        )
    else:
        txt = (
            "📘 הוראות PO:\n"
            f"1) פתח {APP.po_asset}.\n"
            f"2) Chart Mode: Line (אין TF).\n"
            f"3) Trade Expiry = {APP.trade_expiry_sec}s.\n"
            f"4) הבוט מנתח חלון = {APP.window_sec}s (מותאם ל-Line).\n"
            "טיפ: איכות 🟩 Strong עדיפה."
        )
    bot.send_message(chat_id, txt, reply_markup=main_menu_markup())

# =================== Handlers ===================
@bot.message_handler(commands=["start"])
def on_start(msg):
    if not allowed(msg): return
    ensure_fetcher(); aggressive_reset()
    _sync_from_tf_trade()
    _print_all(msg.chat.id, "ברוך הבא ל-PO SignalBot 🎯")
    _send_instructions(msg.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📘 הוראות")
def on_instructions(msg):
    _send_instructions(msg.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📊 נכס")
def on_asset(msg):
    bot.send_message(msg.chat.id, f"נכס נוכחי: {APP.po_asset}\nבחר נכס:", reply_markup=types.ReplyKeyboardRemove())
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
    APP.finnhub_symbol = PO_TO_FINNHUB.get(po_name, DEFAULT_SYMBOL)
    bot.answer_callback_query(c.id, text=f"נבחר: {po_name}")
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text=f"נכס נבחר: {po_name} → {APP.finnhub_symbol}",
                          reply_markup=asset_inline_keyboard(page=int(page)))
    _print_all(c.message.chat.id, "הנכס עודכן")
    _send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📈 מצב תרשים")
def on_chartmode(msg):
    bot.send_message(msg.chat.id, "בחר מצב תרשים:", reply_markup=chartmode_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("chart::"))
def on_chartmode_pick(c):
    mode = c.data.split("::")[1]
    APP.chart_mode = mode if mode in CHART_MODES else "CANDLE"
    _sync_from_tf_trade()
    bot.answer_callback_query(c.id, text=f"Chart={APP.chart_mode}")
    _print_all(c.message.chat.id, "מצב התרשים עודכן")
    _send_instructions(c.message.chat.id)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🕒 זמן נר")
def on_candle(msg):
    if APP.chart_mode == "LINE":
        bot.send_message(msg.chat.id, "במצב Line אין זמן נר (TF). בחר ⏳ זמן עסקה או 🪟 חלון ניתוח.")
        return
    bot.send_message(msg.chat.id, "בחר זמן נר:", reply_markup=choices_inline_keyboard("candle"))

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⏳ זמן עסקה")
def on_trade(msg):
    bot.send_message(msg.chat.id, "בחר זמן עסקה:", reply_markup=choices_inline_keyboard("trade"))

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🪟 חלון ניתוח")
def on_window(msg):
    bot.send_message(msg.chat.id, "בחר חלון (או 'חלון ידני…'):", reply_markup=choices_inline_keyboard("window"))

@bot.callback_query_handler(func=lambda c: c.data == "window_manual")
def on_window_manual(c):
    bot.answer_callback_query(c.id)
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text="בחר חלון ידני:", reply_markup=manual_window_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_candle::"))
def on_set_candle(c):
    if APP.chart_mode == "LINE":
        bot.answer_callback_query(c.id, text="ב-Line אין TF")
        return
    sec = int(c.data.split("::")[1])
    APP.candle_tf_sec = sec
    _sync_from_tf_trade()
    bot.answer_callback_query(c.id, text=f"TF={sec}s")
    _print_all(c.message.chat.id, "זמן הנר עודכן")
    _send_instructions(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_trade::"))
def on_set_trade(c):
    sec = int(c.data.split("::")[1])
    APP.trade_expiry_sec = sec
    rec_tf, rec_w = _recommend_from_expiry(sec)
    APP.window_sec = rec_w
    if APP.chart_mode == "CANDLE" and rec_tf is not None:
        APP.candle_tf_sec = int(rec_tf[:-1])  # "60s" -> 60
    STRAT_CFG["WINDOW_SEC"] = float(rec_w)
    STRAT_CFG["EXPIRY"] = f"{sec}s" if sec < 60 else f"{int(sec/60)}m"
    bot.answer_callback_query(c.id, text=f"Expiry={sec}s")
    if APP.chart_mode == "CANDLE":
        bot.send_message(c.message.chat.id, f"התאמה אוטומטית:\nTF מומלץ: {APP.candle_tf_sec}s\nחלון ניתוח: {rec_w}s")
    else:
        bot.send_message(c.message.chat.id, f"התאמה אוטומטית (Line):\nחלון ניתוח: {rec_w}s (אין TF)")
    _print_all(c.message.chat.id, "זמן העסקה עודכן")
    _send_instructions(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_window::"))
def on_set_window(c):
    sec = int(c.data.split("::")[1])
    APP.window_sec = max(10, min(sec, 120))
    _sync_from_window()
    bot.answer_callback_query(c.id, text=f"Window={APP.window_sec}s")
    _print_all(c.message.chat.id, "חלון הניתוח עודכן")
    _send_instructions(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def on_back_main(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "תפריט ראשי:", reply_markup=main_menu_markup())

# ===== סטטוס/ויזואל/סיגנל =====
def _status_header() -> list[str]:
    src = 'LIVE (Finnhub)' if HAS_LIVE_KEY else 'MISSING_API_KEY'
    return [
        f"Source: {src}",
        f"WS Online: {'Yes' if STATE['ws_online'] else 'No'}",
        f"Reconnects: {STATE['reconnects']}",
        f"Msg recv: {STATE['msg_count']}",
    ]

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🛰️ סטטוס")
def on_status(msg):
    now = time.time()
    ticks = list(STATE["ticks"])
    n_total = len(ticks)
    n_win = len([1 for (ts, _) in ticks if now - ts <= STRAT_CFG["WINDOW_SEC"]])
    age_ms = int((now - STATE["last_recv_ts"]) * 1000) if STATE["last_recv_ts"] else None

    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    q = _quality_label(conf, float(dbg.get("align_bonus", 0.0)))
    lines = ["סטטוס"]
    lines += _status_header()
    lines += [
        f"Last tick age: {age_ms if age_ms is not None else 'n/a'} ms",
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Chart Mode: {APP.chart_mode}",
        f"TF (Chart): {APP.candle_tf_sec}s" if APP.chart_mode == "CANDLE" else "TF (Chart): N/A (Line)",
        f"Trade Expiry: {APP.trade_expiry_sec}s",
        f"Analysis Window: {int(STRAT_CFG['WINDOW_SEC'])}s",
        f"Window ticks: {n_win}/{n_total}",
        f"Signal: {side}",
        f"Confidence: {conf}%",
        f"Quality: {q}",
        f"RSI: {_fmt(dbg.get('rsi'), '.1f')}",
        f"Vol: {_fmt(dbg.get('vol'), '.2e')}",
        f"EMA spread: {_fmt(dbg.get('ema_spread'))}",
        f"Trend slope: {_fmt(dbg.get('trend_slope'))}",
        f"Persistence: {_fmt(dbg.get('persist'), '.2f')}",
        f"Tick imbalance: {_fmt(dbg.get('tick_imb'), '.2f')}",
        f"Align bonus: {_fmt(dbg.get('align_bonus'), '.2f')}",
        "",
        "Auto-Trading",
    ]
    lines += AUTO.status_lines()
    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🖼️ ויזואל")
def on_visual(msg):
    png = make_explained_price_png(STATE["ticks"], STRAT_CFG["WINDOW_SEC"], APP.po_asset)
    cap = "גרף מחיר בחלון האחרון (X=sec, Y=price מלא). קו מקווקו = מחיר נוכחי."
    bot.send_photo(msg.chat.id, png, caption=cap, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🧠 סיגנל")
def on_signal(msg):
    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    q = _quality_label(conf, float(dbg.get("align_bonus", 0.0)))
    arrow = "🔼" if side == "UP" else "🔽" if side == "DOWN" else "⏳"
    lines = [
        "סיגנל",
        f"Asset: {APP.po_asset}",
        f"Symbol: {APP.finnhub_symbol}",
        f"Chart Mode: {APP.chart_mode}",
        (f"TF: {APP.candle_tf_sec}s") if APP.chart_mode == "CANDLE" else "TF: N/A (Line)",
        f"Expiry: {APP.trade_expiry_sec}s",
        f"Window: {int(STRAT_CFG['WINDOW_SEC'])}s",
        f"Decision: {side} {arrow}",
        f"Confidence: {conf}%",
        f"Quality: {q}",
        f"RSI: {_fmt(dbg.get('rsi'), '.1f')} | Vol: {_fmt(dbg.get('vol'), '.2e')}",
        f"ema_spread: {_fmt(dbg.get('ema_spread'))} | slope: {_fmt(dbg.get('trend_slope'))}",
        f"persist: {_fmt(dbg.get('persist'), '.2f')} | tick_imb: {_fmt(dbg.get('tick_imb'), '.2f')} | align_bonus: {_fmt(dbg.get('align_bonus'), '.2f')}",
        "סמן הצלחה/כישלון לאחר פקיעה כדי לשפר את הסטטיסטיקה.",
    ]
    png = make_explained_price_png(STATE["ticks"], STRAT_CFG["WINDOW_SEC"], APP.po_asset)
    bot.send_photo(msg.chat.id, png, caption="\n".join(lines), reply_markup=signal_feedback_keyboard())
    APP.last_signal = {
        "ts": time.time(),
        "asset": APP.po_asset,
        "symbol": APP.finnhub_symbol,
        "side": side,
        "conf": conf,
        "tf": APP.candle_tf_sec if APP.chart_mode=="CANDLE" else None,
        "expiry": APP.trade_expiry_sec,
        "window": APP.window_sec,
        "mode": APP.chart_mode,
    }

@bot.callback_query_handler(func=lambda c: c.data in ("sig::hit","sig::miss"))
def on_signal_feedback(c):
    if APP.last_signal is None:
        bot.answer_callback_query(c.id, text="אין סיגנל אחרון לסימון.")
        return
    day = _today_key()
    if c.data == "sig::hit":
        APP.daily_hits[day] += 1
        bot.answer_callback_query(c.id, text="סומן: ✅ פגיעה")
    else:
        APP.daily_miss[day] += 1
        bot.answer_callback_query(c.id, text="סומן: ❌ החטאה")

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📈 ביצועים")
def on_performance(msg):
    day = _today_key()
    hits = APP.daily_hits[day]
    miss = APP.daily_miss[day]
    total = hits + miss
    wr = (100.0*hits/total) if total>0 else 0.0
    lines = [
        "ביצועים (היום)",
        f"Hits (✅): {hits}",
        f"Misses (❌): {miss}",
        f"Total: {total}",
        f"Win-Rate: {_fmt(wr, '.1f')}%",
        "טיפ: שקול לפעול רק כשConfidence≥70/75 כדי לשפר יחס פגיעה.",
    ]
    bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=main_menu_markup())

# ===== מסחר אוטומטי: תפעול =====
@bot.message_handler(func=lambda m: allowed(m) and m.text == "🤖 מסחר אוטומטי")
def on_auto_toggle(msg):
    if AUTO.state.enabled:
        AUTO.disable()
        bot.send_message(msg.chat.id, "Auto-Trading: OFF", reply_markup=main_menu_markup())
    else:
        AUTO.enable()
        bot.send_message(msg.chat.id, "Auto-Trading: ON", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⚙️ Auto-Settings")
def on_auto_settings(msg):
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("Conf −5", callback_data="auto::conf:-5"),
        types.InlineKeyboardButton("Conf +5", callback_data="auto::conf:+5"),
    )
    kb.row(
        types.InlineKeyboardButton("Interval −5s", callback_data="auto::ival:-5"),
        types.InlineKeyboardButton("Interval +5s", callback_data="auto::ival:+5"),
    )
    kb.add(types.InlineKeyboardButton("סטטוס אוטו", callback_data="auto::status"))
    bot.send_message(msg.chat.id, "שנה סף ביטחון/מרווח זמן:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("auto::"))
def on_auto_cb(c):
    _, kind, val = c.data.split("::")
    if kind == "conf":
        AUTO.set_conf_threshold(AUTO.state.conf_threshold + int(val))
        bot.answer_callback_query(c.id, text=f"Conf ≥ {AUTO.state.conf_threshold}")
    elif kind == "ival":
        AUTO.set_min_interval(AUTO.state.min_interval_sec + int(val))
        bot.answer_callback_query(c.id, text=f"Interval = {AUTO.state.min_interval_sec}s")
    elif kind == "status":
        bot.answer_callback_query(c.id, text="Auto status")
    bot.edit_message_text(
        chat_id=c.message.chat.id,
        message_id=c.message.message_id,
        text="\n".join(AUTO.status_lines()),
        reply_markup=None
    )

# ===== לולאת החלטה רקע למסחר אוטומטי =====
def auto_loop():
    while True:
        try:
            if AUTO.state.enabled:
                side, conf, _dbg = decide_from_ticks(STATE["ticks"])
                if side in ("UP","DOWN") and conf >= AUTO.state.conf_threshold:
                    AUTO.place_trade(side)
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
    bot.send_message(msg.chat.id, "PANIC: webhook נוקה. יוצא.")
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
                print("[409] cleaning webhook & retry"); aggressive_reset(); continue
            print("ApiTelegramException:", e); time.sleep(2)
        except Exception as e:
            print("polling exception:", e); time.sleep(2)

def main():
    ensure_single_instance()
    ensure_fetcher()
    _sync_from_tf_trade()   # סינכרון ראשוני
    t = threading.Thread(target=auto_loop, daemon=True)
    t.start()
    run_forever()

if __name__ == "__main__":
    main()
