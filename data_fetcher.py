from __future__ import annotations
import json, time, threading, asyncio, os, collections
from typing import List, Tuple
import websockets

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "").strip()
HAS_LIVE_KEY = bool(FINNHUB_KEY)

STATE = {
    "ticks": collections.deque(maxlen=8000),
    "lock": threading.Lock(),
    "ws_online": False,
    "used_symbol": None,
    "msg_count": 0,
    "last_recv_ts": 0.0,
    "reconnects": 0,
    "ws_url": None,
    "subscribed": [],
    "current_finnhub_symbol": None,
}

def _url_for_symbol(sym: str) -> str:
    return f"wss://ws.finnhub.io?token={FINNHUB_KEY}"

async def _consumer(sym: str):
    url = _url_for_symbol(sym)
    STATE["ws_url"] = url
    STATE["current_finnhub_symbol"] = sym
    async with websockets.connect(url, ping_interval=15, ping_timeout=15) as ws:
        await ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
        STATE["subscribed"] = [sym]
        STATE["ws_online"] = True
        while True:
            msg = await ws.recv()
            STATE["msg_count"] += 1
            STATE["last_recv_ts"] = time.time()
            data = json.loads(msg)
            if data.get("type") == "trade":
                for d in data.get("data", []):
                    if d.get("s") != sym:
                        continue
                    price = float(d.get("p"))
                    STATE["used_symbol"] = sym
                    with STATE["lock"]:
                        STATE["ticks"].append((time.time(), price))
                        
async def _main_loop(sym_getter):
    if not HAS_LIVE_KEY:
        STATE["ws_online"] = False
        while True:
            await asyncio.sleep(1.0)

    backoff = 2
    max_backoff = 30
    while True:
        sym = sym_getter()
        try:
            await _consumer(sym)
        except Exception:
            STATE["ws_online"] = False
            STATE["reconnects"] += 1
            await asyncio.sleep(backoff)
            backoff = min(max_backoff, backoff * 2)

def start_fetcher_in_thread(sym_getter):
    t = threading.Thread(
        target=lambda: asyncio.new_event_loop().run_until_complete(_main_loop(sym_getter)),
        daemon=True
    )
    t.start()
