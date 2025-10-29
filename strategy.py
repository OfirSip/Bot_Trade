# strategy.py
from __future__ import annotations
import math, time
from typing import Tuple, Dict, List
from indicators import ema_alpha, rsi, simple_vol, slope

# היפר-פרמטרים (ניתנים לשינוי דרך תפריט ״⚙️ הגדרות״)
CFG = {
    "WINDOW_SEC": 22.0,   # חלון ניתוח לטיקרים
    "ALPHA_FAST": 0.35,   # EMA מהיר על log-changes
    "ALPHA_SLOW": 0.12,   # EMA איטי
    "RSI_PERIOD": 14,
    "RSI_BULL": 52.0,     # מעל -> עדיפות LONG
    "RSI_BEAR": 48.0,     # מתחת -> עדיפות SHORT
    "CONF_MIN": 55,       # מינימום confidence להחזרה
    "CONF_MAX": 95,       # תקרה
    "VOL_GUARD": 1e-4,    # מתחת לזה → להוריד אמון (שוק "ישנוני")
    "EXPIRY": "M1",       # M1/M3
}

def compute_signal_from_prices(prices: List[float]) -> Tuple[str, int, Dict]:
    if not prices or len(prices) < 4:
        return "WAIT", 50, {"reason": "insufficient_data"}

    base = prices[0]
    changes = [math.log(max(1e-12, p / base)) for p in prices]
    diffs   = [changes[i] - changes[i-1] for i in range(1, len(changes))]

    ema_f = ema_alpha(changes, CFG["ALPHA_FAST"])
    ema_s = ema_alpha(changes, CFG["ALPHA_SLOW"])
    tr_slope = slope(changes)
    vol = simple_vol(diffs)

    # raw score: שילוב EMA הפרדה + שיפוע
    raw = 0.55*(ema_f - ema_s) + 0.45*tr_slope
    norm = abs(raw) / vol
    rsi_v = rsi(prices, CFG["RSI_PERIOD"])

    # פילטר כיוון לפי RSI
    if rsi_v >= CFG["RSI_BULL"]:
        direction_bias = 1.0
    elif rsi_v <= CFG["RSI_BEAR"]:
        direction_bias = -1.0
    else:
        direction_bias = 0.0  # ניטרלי (לא "הורג", רק משפיע על confidence)

    # confidence
    conf_f = 50 + 40*math.tanh(norm)   # 50..~90
    # guard לשוק איטי
    if vol < CFG["VOL_GUARD"]:
        conf_f -= 8.0

    # bias מוסיף/מוריד קצת, לא מחליף כיוון
    conf_f += 3.0*direction_bias
    conf = int(max(CFG["CONF_MIN"], min(CFG["CONF_MAX"], conf_f)))

    # החלטת כיוון
    if raw > 0:
        side = "UP"
    elif raw < 0:
        side = "DOWN"
    else:
        side = "UP" if prices[-1] >= prices[-2] else "DOWN"

    # אם אין מספיק אמון — WAIT (כדי לא לירות סתם)
    if conf < CFG["CONF_MIN"]:
        return "WAIT", conf, {
            "vol": vol, "rsi": rsi_v, "ema_fast": ema_f, "ema_slow": ema_s,
            "raw": raw, "norm": norm, "reason": "below_conf_min"
        }

    dbg = {
        "n": len(prices), "price_now": prices[-1], "price_min": min(prices), "price_max": max(prices),
        "vol": vol, "rsi": rsi_v, "ema_fast": ema_f, "ema_slow": ema_s,
        "raw": raw, "norm": norm, "expiry": CFG["EXPIRY"]
    }
    return side, conf, dbg

def decide_from_ticks(ticks_deque) -> Tuple[str, int, Dict]:
    now = time.time()
    window = [p for (ts, p) in list(ticks_deque) if now - ts <= CFG["WINDOW_SEC"]]
    if len(window) < 10:
        window = [p for (_, p) in list(ticks_deque)[-10:]]
    return compute_signal_from_prices(window)
