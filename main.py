# main.py
from __future__ import annotations
import os, sys, time, socket
import telebot
from telebot import types
from telebot.apihelper import delete_webhook, ApiTelegramException

from pocket_map import PO_TO_FINNHUB, DEFAULT_SYMBOL, SUPPORTED_EXPIRIES
from data_fetcher import STATE, start_fetcher_in_thread
from strategy import decide_from_ticks, CFG as STRAT_CFG
from visuals import make_price_figure_png

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_LOCK = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SINGLETON_PORT = int(os.getenv("SINGLETON_PORT", "47653"))
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ------------------------ anti-409 & single-instance ------------------------
def aggressive_reset():
    try: bot.remove_webhook()
    except Exception: pass
    try: delete_webhook(BOT_TOKEN, drop_pending_updates=True)
    except Exception: pass
    time.sleep(0.8)

_LOCK = None
def ensure_single_instance(port: int = SINGLETON_PORT):
    global _LOCK
    _LOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _LOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        _LOCK.bind(("127.0.0.1", port))
        _LOCK.listen(1)
    except OSError:
        print("Another instance running. Exiting.")
        sys.exit(0)

# ------------------------ Bot State ------------------------
class BotState:
    def __init__(self):
        self.po_asset: str = "EUR/USD"
        self.finnhub_symbol: str = PO_TO_FINNHUB.get(self.po_asset, DEFAULT_SYMBOL)

APP = BotState()

def current_symbol():
    return APP.finnhub_symbol

# start fetcher thread once
_fetcher_started = False
def ensure_fetcher():
    global _fetcher_started
    if not _fetcher_started:
        start_fetcher_in_thread(lambda: current_symbol())
        _fetcher_started = True

def allowed(msg) -> bool:
    return (not CHAT_LOCK) or (str(msg.chat.id) == CHAT_LOCK)

# ------------------------ UI helpers ------------------------
def main_menu_markup():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📊 נכס"),
        types.KeyboardButton("⚙️ הגדרות"),
    )
    kb.add(
        types.KeyboardButton("🛰️ סטטוס"),
        types.KeyboardButton("🖼️ ויזואל"),
    )
    kb.add(types.KeyboardButton("🧠 סיגנל"))
    return kb

def asset_inline_keyboard(page: int = 0, page_size: int = 6):
    keys = list(PO_TO_FINNHUB.keys())
    start = page * page_size
    chunk = keys[start:start+page_size]
    markup = types.InlineKeyboardMarkup()
    for k in chunk:
        markup.add(types.InlineKeyboardButton(f"🎯 {k}", callback_data=f"asset::{k}::{page}"))
    # pagination
    nav = []
    if start > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"asset_nav::{page-1}"))
    if start + page_size < len(keys):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"asset_nav::{page+1}"))
    if nav:
        markup.row(*nav)
    return markup

def settings_inline_keyboard():
    markup = types.InlineKeyboardMarkup()
    # expiry
    exp_row = [types.InlineKeyboardButton(f"{'✅ ' if STRAT_CFG['EXPIRY']==e else ''}{e}", callback_data=f"set_expiry::{e}") for e in SUPPORTED_EXPIRIES]
    markup.row(*exp_row)
    # window
    markup.add(types.InlineKeyboardButton(f"חלון ⏱ {int(STRAT_CFG['WINDOW_SEC'])}s", callback_data="noop"))
    markup.row(
        types.InlineKeyboardButton("-2s", callback_data="win::dec"),
        types.InlineKeyboardButton("+2s", callback_data="win::inc"),
    )
    # conf min
    markup.add(types.InlineKeyboardButton(f"MinConf 🎯 {STRAT_CFG['CONF_MIN']}%", callback_data="noop"))
    markup.row(
        types.InlineKeyboardButton("-2", callback_data="conf::dec"),
        types.InlineKeyboardButton("+2", callback_data="conf::inc"),
    )
    # reset
    markup.add(types.InlineKeyboardButton("🔄 ברירת מחדל", callback_data="reset_cfg"))
    return markup

# ------------------------ Handlers ------------------------
@bot.message_handler(commands=["start"])
def on_start(msg):
    if not allowed(msg): return
    ensure_fetcher()
    aggressive_reset()
    bot.send_message(msg.chat.id,
        "ברוך הבא ל-**PO SignalBot** 🚀\n"
        "בחר נכס, קבע הגדרות, וצא לדרך.\n\n"
        "טיפ: חפש התאמה בין הוויזואל לשוק בפועל ב-Pocket Option לפני כניסה.",
        reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "📊 נכס")
def on_asset(msg):
    bot.send_message(msg.chat.id, f"נכס נוכחי: **{APP.po_asset}**\nבחר נכס:", reply_markup=types.ReplyKeyboardRemove())
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
                          text=f"🎯 נכס נבחר: **{po_name}** → {APP.finnhub_symbol}",
                          reply_markup=asset_inline_keyboard(page=int(page)))
    bot.send_message(c.message.chat.id, "חוזרים לתפריט ⬇️", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "⚙️ הגדרות")
def on_settings(msg):
    txt = (
        f"⚙️ הגדרות נוכחיות\n"
        f"- Expiry: {STRAT_CFG['EXPIRY']}\n"
        f"- חלון: {int(STRAT_CFG['WINDOW_SEC'])}s\n"
        f"- MinConf: {STRAT_CFG['CONF_MIN']}%\n"
    )
    bot.send_message(msg.chat.id, txt, reply_markup=settings_inline_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_expiry::"))
def on_set_expiry(c):
    exp = c.data.split("::")[1]
    STRAT_CFG["EXPIRY"] = exp
    bot.answer_callback_query(c.id, text=f"Expiry: {exp}")
    on_settings(c.message)

@bot.callback_query_handler(func=lambda c: c.data in ("win::dec","win::inc","conf::dec","conf::inc","reset_cfg","noop"))
def on_cfg_adjust(c):
    k = c.data
    if k == "win::dec": STRAT_CFG["WINDOW_SEC"] = max(10.0, STRAT_CFG["WINDOW_SEC"] - 2.0)
    if k == "win::inc": STRAT_CFG["WINDOW_SEC"] = min(60.0, STRAT_CFG["WINDOW_SEC"] + 2.0)
    if k == "conf::dec": STRAT_CFG["CONF_MIN"] = max(50, STRAT_CFG["CONF_MIN"] - 2)
    if k == "conf::inc": STRAT_CFG["CONF_MIN"] = min(90, STRAT_CFG["CONF_MIN"] + 2)
    if k == "reset_cfg":
        STRAT_CFG.update({"WINDOW_SEC":22.0,"CONF_MIN":55,"EXPIRY":"M1"})
    bot.answer_callback_query(c.id)
    on_settings(c.message)

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🛰️ סטטוס")
def on_status(msg):
    now = time.time()
    ticks = list(STATE["ticks"])
    n_total = len(ticks)
    n_win = len([1 for (ts,_) in ticks if now - ts <= STRAT_CFG["WINDOW_SEC"]])
    age_ms = int((now - STATE["last_recv_ts"]) * 1000) if STATE["last_recv_ts"] else None
    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    text = (
        f"📡 **סטטוס דאטה**: {'✅ Online' if STATE['ws_online'] else '⚠️ Offline'} | Reconnects: {STATE['reconnects']}\n"
        f"🔗 Symbol: {APP.finnhub_symbol} (PO: {APP.po_asset})\n"
        f"📥 Msg recv: {STATE['msg_count']} | Last tick age: {age_ms} ms\n"
        f"🪟 Window({int(STRAT_CFG['WINDOW_SEC'])}s): {n_win}/{n_total} ticks\n\n"
        f"🧮 **ניתוח** (expiry {STRAT_CFG['EXPIRY']}):\n"
        f"- Decision: {side} {'🔼' if side=='UP' else '🔽' if side=='DOWN' else '⏳'}\n"
        f"- Confidence: {conf}%\n"
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🖼️ ויזואל")
def on_visual(msg):
    png = make_price_figure_png(list(STATE["ticks"]), window_sec=STRAT_CFG["WINDOW_SEC"])
    bot.send_photo(msg.chat.id, png, caption="📷 חלון מחירים נוכחי (בדוק התאמה ב-PO)", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: allowed(m) and m.text == "🧠 סיגנל")
def on_signal(msg):
    side, conf, dbg = decide_from_ticks(STATE["ticks"])
    arrow = "🔼" if side == "UP" else "🔽" if side == "DOWN" else "⏳"
    cap = (
        f"🧠 **סיגנל**\n"
        f"נכס: {APP.po_asset} → {APP.finnhub_symbol}\n"
        f"Expiry: {STRAT_CFG['EXPIRY']}\n"
        f"Decision: {side} {arrow}\n"
        f"Confidence: {conf}%\n"
        f"RSI: {dbg.get('rsi'):.1f} | Vol: {dbg.get('vol'):.2e}\n"
        f"עצה: וודא ב-PO שהגרף מראה אותו כיוון/תנודתיות לפני כניסה ✅"
    )
    png = make_price_figure_png(list(STATE["ticks"]), window_sec=STRAT_CFG["WINDOW_SEC"])
    bot.send_photo(msg.chat.id, png, caption=cap, parse_mode="Markdown", reply_markup=main_menu_markup())

@bot.message_handler(commands=["panic"])
def on_panic(msg):
    if not allowed(msg): return
    try: bot.remove_webhook()
    except Exception: pass
    try: delete_webhook(BOT_TOKEN, drop_pending_updates=True)
    except Exception: pass
    bot.send_message(msg.chat.id, "🧯 PANIC: webhook נוקה. מבצע יציאה.")
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
    run_forever()

if __name__ == "__main__":
    main()
