from __future__ import annotations
import os, time, json, threading, websocket, traceback, ssl
from collections import deque

###############################################################################
# DATA FETCHER
# גרסה משופרת עם:
# - Auto reconnect מלא
# - Watchdog פנימי (בודק אם אין נתונים ומבצע reset)
# - התאוששות חלקה מריבוי ניתוקים (Finnhub)
# - Thread-safe
###############################################################################

# ============================================================
# הגדרות ENV
# ============================================================
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "").strip()
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "OANDA:EUR_USD")

# ============================================================
# מצב משותף לכל המערכת
# ============================================================
STATE = {
    "ticks": deque(maxlen=1500),
    "ws_online": False,
    "last_recv_ts": 0.0,
    "reconnects": 0,
    "msg_count": 0,
}

# ============================================================
# פונקציה פנימית לניקוי וסטארט חדש
# ============================================================
def _reset_state():
    STATE["ticks"].clear()
    STATE["ws_online"] = False
    STATE["msg_count"] = 0
    STATE["last_recv_ts"] = 0.0
    STATE["reconnects"] += 1


# ============================================================
# פונקציית Watchdog
# ============================================================
def _watchdog_thread(ws_ref, symbol_getter):
    """
    מנטר את ה-WebSocket ומבצע reconnect אם אין נתונים.
    """
    while True:
        try:
            time.sleep(15)
            now = time.time()
            last = STATE["last_recv_ts"]
            if now - last > 60:  # אין נתונים מעל דקה
                print("[WATCHDOG] no data >60s -> reconnecting")
                try:
                    ws = ws_ref.get("ws")
                    if ws:
                        ws.close()
                except Exception:
                    pass
                start_fetcher_in_thread(symbol_getter, force_restart=True)
        except Exception:
            traceback.print_exc()
            time.sleep(10)


# ============================================================
# Callback handlers
# ============================================================

def on_open(ws):
    STATE["ws_online"] = True
    print("[WS] Connected to Finnhub")


def on_close(ws, close_status_code, close_msg):
    print("[WS] Closed:", close_status_code, close_msg)
    STATE["ws_online"] = False


def on_error(ws, error):
    print("[WS] Error:", error)
    STATE["ws_online"] = False


def on_message(ws, message):
    try:
        data = json.loads(message)
        if not isinstance(data, dict):
            return
        if data.get("type") == "trade":
            for item in data.get("data", []):
                ts = item.get("t", 0) / 1000.0
                price = float(item.get("p", 0))
                STATE["ticks"].append((ts, price))
                STATE["msg_count"] += 1
                STATE["last_recv_ts"] = time.time()
    except Exception as e:
        print("[WS] parse error:", e)


# ============================================================
# Worker
# ============================================================
def _fetcher_worker(symbol_getter, ws_ref):
    """
    חיבור מתמשך ל-Finnhub עם ניהול שגיאות וחיבורים מחדש.
    """
    while True:
        symbol = symbol_getter()
        if not symbol:
            print("[Fetcher] No symbol provided, sleeping...")
            time.sleep(5)
            continue

        try:
            if not FINNHUB_KEY:
                print("[Fetcher] Missing FINNHUB_KEY")
                time.sleep(10)
                continue

            url = f"wss://ws.finnhub.io?token={FINNHUB_KEY}"
            print(f"[Fetcher] Connecting to {url} ...")

            ws = websocket.WebSocketApp(
                url,
                on_open=on_open,
                on_close=on_close,
                on_message=on_message,
                on_error=on_error
            )

            ws_ref["ws"] = ws

            def _subscribe():
                payload = {"type": "subscribe", "symbol": symbol}
                try:
                    ws.send(json.dumps(payload))
                    print(f"[Fetcher] Subscribed to {symbol}")
                except Exception as e:
                    print("[Fetcher] subscribe error:", e)

            wst = threading.Thread(target=ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True)
            wst.start()

            time.sleep(2)
            _subscribe()

            while True:
                if not ws.sock or not ws.sock.connected:
                    raise ConnectionError("Socket disconnected")
                time.sleep(5)

        except Exception as e:
            print("[Fetcher] Exception:", e)
            traceback.print_exc()
            STATE["ws_online"] = False
            _reset_state()
            time.sleep(5)
            continue


# ============================================================
# API החיצונית
# ============================================================
def start_fetcher_in_thread(symbol_getter, force_restart=False):
    """
    מפעיל את איסוף הנתונים על גבי Thread חדש.
    symbol_getter = פונקציה שמחזירה את הסימבול הנוכחי (למשל 'OANDA:EUR_USD')
    """
    static_ref = getattr(start_fetcher_in_thread, "_ref", {"ws": None})
    if force_restart:
        try:
            ws = static_ref.get("ws")
            if ws:
                ws.close()
        except Exception:
            pass
        static_ref["ws"] = None

    if getattr(start_fetcher_in_thread, "_thread", None) and start_fetcher_in_thread._thread.is_alive():
        return  # כבר רץ

    t = threading.Thread(target=_fetcher_worker, args=(symbol_getter, static_ref), daemon=True)
    t.start()
    start_fetcher_in_thread._thread = t
    start_fetcher_in_thread._ref = static_ref

    # הפעלת watchdog נפרד
    wd = threading.Thread(target=_watchdog_thread, args=(static_ref, symbol_getter), daemon=True)
    wd.start()

    print("[Fetcher] started thread and watchdog")
