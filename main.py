# main.py
from __future__ import annotations
import os, sys, time, socket, io
import telebot
from telebot import types
from telebot.apihelper import delete_webhook, ApiTelegramException

from pocket_map import PO_TO_FINNHUB, DEFAULT_SYMBOL
from data_fetcher import STATE, start_fetcher_in_thread, HAS_LIVE_KEY
from strategy import decide_from_ticks, CFG as STRAT_CFG

# ========== Matplotlib (גרף פשוט ומוסבר) ==========
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

# ---------- הגדרות משתמש (2 פרמטרים בלבד) ----------
CANDLE_CHOICES = [
    ("10s", 10), ("15s", 15), ("30s", 30),
    ("1m", 60), ("2m", 120), ("3m", 180), ("5m", 300),
]
TRADE_CHOICES = [
    ("10s", 10), ("30s", 30),
    ("1m", 60), ("2m", 120), ("3m", 180), ("5m", 300)
]

class BotState:
    def __init__(self):
        self.po_asset: str = "EUR/USD"
        self.finnhub_symbol: str = PO_TO_FINNHUB.get(self.po_asset, DEFAULT_SYMBOL)
        self.candle_tf_sec: int = 60      # זמן נר ברירת מחדל: 1m
        self.trade_expiry_sec: int = 60   # זמן עסקה ברירת מחדל: 1m

APP = BotState()
_fetcher_started = False

# ---------- ENV ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_LOCK = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SINGLETON_PORT = int(os.getenv("SINGLETON_PORT", "47653"))
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)  # בלי Markdown/HTML

# ---------- Anti-409 & single-instance ----------
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

# ---------- עזרי תצוגה ----------
def _fmt(x, fmt=".4g"):
    try:
        return format(float(x), fmt)
    except Exception:
        return "n/a"

def _price_decimals(po_asset: str) -> int:
    a = po_asset.upper()
    if "BTC" in a or "ETH" in a:
        return 2
    if "JPY" in a:
        return 3
    return 5

def make_explained_price_png(ticks, window_sec: float, po_asset: str):
    """
    גרף: קו מחיר בחלון האחרון, קו אופקי למחיר נוכחי, מקרא וצירים ברורים.
    X: שניות (אמיתי), Y: מחיר מלא עם ספרות מתאימות לנכס.
    """
    now = time.time()
    win = [(ts, p) for (ts, p) in list(ticks) if now - ts <= window_sec]
    if len(win) < 6:
        win = list(ticks)[-6:]
    buf = io.BytesIO()
    fig = plt.figure(figsize=(6.4, 3.2))

    if not win:
        plt.title("No data yet")
        plt.xlabel("time [sec]")
        plt.ylabel("price")
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=140)
        plt.close(fig)
        return buf.getvalue()

    xs = [ts - win[0][0] for (ts, _) in win]   # שניות יחסיות
    ys = [p for (_, p) in win]
    last_price = ys[-1]

    # קו המחיר
    line, = plt.plot(xs, ys, linewidth=2.0, label="Price")
    # קו אופקי למחיר נוכחי
    ref = plt.axhline(last_price, linestyle="--", linewidth=1.2, label="Last Price")

    # עיצוב צירים
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

# ---------- בניית מקלדות ----------
def main_menu_markup():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton("📊 נכס"))
    kb.add(types.KeyboardButton("🕒 זמן נר"), types.KeyboardButton("⏳ זמן עסקה"))
    kb.add(types.KeyboardButton("🛰️ סטטוס"), types.KeyboardButton("🖼️ ויזואל"))
    kb.add(types.KeyboardButton("🧠 סיגנל"))
    return kb

def asset_inline_keyboard(page: int = 0, page_size: int = 6):
    keys = list(PO_TO_FINNHUB.keys())
    start = page * page_size
    chunk = keys[start:start + page_size]
    markup = types.InlineKeyboardMarkup()
    for k in chunk:
        markup.add(types.InlineKeyboardButton(f"🎯 {k}", callback_data=f"asset::{k}::{page}"))
    nav = []
    if start > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"asset_nav::{page-1}"))
    if start + page_size < len(keys):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"asset_nav::{page+1}"))
    if nav:
        markup.row(*nav)
    return markup

def choices_inline_keyboard(kind: str):
    # kind in {"candle","trade"}
    markup = types.InlineKeyboardMarkup()
    choices = CANDLE_CHOICES if kind == "candle" else TRADE_CHOICES
    row = []
    for label, sec in choices:
        row.append(types.InlineKeyboardButton(label, callback_data=f"set_{kind}::{sec}"))
        if len(row) == 4:
            markup.row(*row); row = []
    if row:
        markup.row(*row)
    markup.add(types.InlineKeyboardButton("חזרה לתפריט", callback_data="back_main"))
    return markup

# ---------- סנכרון חלון ניתוח לפי הבחירות ----------
def recompute_window():
    """
    חלון ניתוח (WINDOW_SEC) נגזר מהעדפות:
    - לפחות 3 נרות של ה-Timeframe שנבחר
    - לפחות 80% מזמן העסקה
    - גבולות ברירת מחדל: 16..90 שניות
    """
    tf = APP.candle_tf_sec
    tx = APP.trade_expiry_sec
    wnd = max(3*tf, 0.8*tx)
    wnd = max(16, min(int(round(wnd)), 90))
    STRAT_CFG["WINDOW_SEC"] = float(wnd)
    # שמירה טקסטואלית של Expiry להצגה
    STRAT_CFG["EXPIRY"] = f"{tx}s" if tx < 60 else f"{int(tx/60)}m"

def notify_po_params(chat_id: int):
    msg = (
        "הגדרות מעודכנות:\n"
        f"- זמן נר (PO Chart TF): {APP.candle_tf_sec}s\n"
        f"- זמן עסקה (Expiry): {APP.trade_expiry_sec}s\n"
        f"- חלון ניתוח (Bot WINDOW): {int(STRAT_CFG['WINDOW_SEC'])}s\n\n"
        "ב-PO הגדר:\n"
        f"• Chart timeframe = {APP.candle_tf_sec}s\n"
        f"• Trade expiry = {APP.trade_expiry_sec}s\n"
        "הבוט מתאים את חלון הניתוח אוטומטית."
    )
    bot.send_message(chat_id, msg, reply_markup=main_menu_markup())

# =================== Handlers ===================
@bot.message_handler(commands=["start"])
def on_start(msg):
    if not allowed(msg): return
    ensure_fetcher()
    aggressive_reset()
    # Sync initial window
    recompute_window()
    bot.send_message(
        msg.chat.id,
        "ברוך הבא ל-PO SignalBot 🎯\nבחר '🕒 זמן נר' ו-'⏳ זמן עסקה'. אני אכוון אוטומטית את חלון הניתוח ואשלח לך הנחיה ל-PO.",
        reply_markup=main_menu_markup()
    )

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
    bot.send_message(c.message.chat.id, "חוזרים לתפריט ⬇️", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🕒 זמן נר")
def on_candle(msg):
    txt = (
        "בחר זמן נר (Chart TF):\n"
        "10s • 15s • 30s • 1m • 2m • 3m • 5m"
    )
    bot.send_message(msg.chat.id, txt, reply_markup=choices_inline_keyboard("candle"))

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⏳ זמן עסקה")
def on_trade(msg):
    txt = (
        "בחר זמן עסקה (Expiry):\n"
        "10s • 30s • 1m • 2m • 3m • 5m"
    )
    bot.send_message(msg.chat.id, txt, reply_markup=choices_inline_keyboard("trade"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_candle::"))
def on_set_candle(c):
    sec = int(c.data.split("::")[1])
    APP.candle_tf_sec = sec
    recompute_window()
    bot.answer_callback_query(c.id, text=f"TF={sec}s")
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text=f"זמן נר עודכן ל-{sec}s")
    notify_po_params(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_trade::"))
def on_set_trade(c):
    sec = int(c.data.split("::")[1])
    APP.trade_expiry_sec = sec
    recompute_window()
    bot.answer_callback_query(c.id, text=f"Expiry={sec}s")
    bot.edit_message_text(chat_id=c.message.chat.id, message_id=c.message.message_id,
                          text=f"זמן עסקה עודכן ל-{sec}s")
    notify_po_params(c.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def on_back_main(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "תפריט ראשי:", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🛰️ סטטוס")
def on_status(msg):
    now = time.time()
    ticks = list(STATE["ticks"])
    n_total = len(ticks)
    n_win = len([1 for (ts, _) in ticks if now - ts <= STRAT_CFG["WINDOW_SEC"]])
    age_ms = int((now - STATE["last_recv_ts"]) * 1000) if STATE["last_recv_ts"] else None

    side, conf, dbg = decide_from_ticks(STATE["ticks"])

    source = "LIVE (Finnhub)" if HAS_LIVE_KEY else "MISSING_API_KEY"
    online = 'Online' if STATE['ws_online'] else 'Offline'

    text = (
        f"סטטוס דאטה: {online} | Source: {source} | Reconnects: {STATE['reconnects']}\n"
        f"Symbol: {APP.finnhub_symbol} (PO: {APP.po_asset})\n"
        f"Msg recv: {STATE['msg_count']} | Last tick age: {age_ms if age_ms is not None else 'n/a'} ms\n"
        f"Window({int(STRAT_CFG['WINDOW_SEC'])}s): {n_win}/{n_total} ticks\n\n"
        f"ניתוח (Trade={APP.trade_expiry_sec}s, TF={APP.candle_tf_sec}s):\n"
        f"- Signal: {side}\n"
        f"- Confidence: {conf}%\n"
        f"- RSI: {_fmt(dbg.get('rsi'), '.1f')} | Vol: {_fmt(dbg.get('vol'), '.2e')} | Regime: {dbg.get('regime','n/a')}\n"
        f"- EMA spread: {_fmt(dbg.get('ema_spread'))} | Trend slope: {_fmt(dbg.get('trend_slope'))}\n"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🖼️ ויזואל")
def on_visual(msg):
    png = make_explained_price_png(STATE["ticks"], STRAT_CFG["WINDOW_SEC"], APP.po_asset)
    caption = (
        "גרף מחירים בחלון האחרון.\n"
        "X: זמן [sec], Y: מחיר מלא. קו מקווקו = המחיר הנוכחי."
    )
    bot.send_photo(msg.chat.id, png, caption=caption, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🧠 סיגנל")
def on_signal(msg):
    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    arrow = "🔼" if side == "UP" else "🔽" if side == "DOWN" else "⏳"
    cap = (
        "סיגנל\n"
        f"נכס: {APP.po_asset} → {APP.finnhub_symbol}\n"
        f"TF={APP.candle_tf_sec}s | Trade={APP.trade_expiry_sec}s | Window={int(STRAT_CFG['WINDOW_SEC'])}s\n"
        f"Decision: {side} {arrow}\n"
        f"Confidence: {conf}%  ({dbg.get('regime','?')}, RSI={_fmt(dbg.get('rsi'), '.1f')})\n"
        f"EMA_spread={_fmt(dbg.get('ema_spread'))} | slope={_fmt(dbg.get('trend_slope'))} | vol={_fmt(dbg.get('vol'), '.2e')}\n"
        "ב-PO: ודא שה-Timeframe וה-Expiry תואמים את ההודעה."
    )
    png = make_explained_price_png(STATE["ticks"], STRAT_CFG["WINDOW_SEC"], APP.po_asset)
    bot.send_photo(msg.chat.id, png, caption=cap, reply_markup=main_menu_markup())

@bot.message_handler(commands=["panic"])
def on_panic(msg):
    if not allowed(msg): return
    try: bot.remove_webhook()
    except Exception: pass
    try: delete_webhook(BOT_TOKEN, drop_pending_updates=True)
    except Exception: pass
    bot.send_message(msg.chat.id, "PANIC: webhook נוקה. יוצא.")
    sys.exit(0)

# ---------- Runner ----------
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
                aggressive_reset(); continue
            print("ApiTelegramException:", e); time.sleep(2)
        except Exception as e:
            print("polling exception:", e); time.sleep(2)

def main():
    ensure_single_instance()
    ensure_fetcher()
    recompute_window()  # sync initial
    run_forever()

if __name__ == "__main__":
    main()
