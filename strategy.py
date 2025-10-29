# strategy.py
from __future__ import annotations
import math, time
from typing import Tuple, Dict, List

# לא תלוי בשאר מודולים פרט לסטנדרט; API נשאר זהה: decide_from_ticks(deque)->(side,conf,dbg)

CFG = {
    "WINDOW_SEC": 26.0,      # מתעדכן מהבוט
    "ALPHA_FAST": 0.40,
    "ALPHA_SLOW": 0.14,
    "RSI_PERIOD": 14,
    "RSI_BULL": 55.0,        # bias LONG
    "RSI_BEAR": 45.0,        # bias SHORT
    "CONF_MIN": 55,          # סף מינימלי להחזרת טרייד
    "CONF_MAX": 96,
    "VOL_GUARD": 8e-5,       # שוק ישנוני מוריד אמון
    "HYSTERESIS": 0.08,      # רצועה נגד ויפסו
    "COOLDOWN_SEC": 12.0,    # לא להפוך מהר
    "NEUTRAL_RSI_LOW": 48.0, # ענישה כש-RSI באזור ניטרלי
    "NEUTRAL_RSI_HIGH": 52.0,
    "EXPIRY": "M1",
}

# --- עזרי חישוב קלים ---
def _log_changes(prices: List[float]) -> List[float]:
    base = prices[0]
    return [math.log(max(1e-12, p / base)) for p in prices]

def _diffs(x: List[float]) -> List[float]:
    return [x[i] - x[i-1] for i in range(1, len(x))] if len(x) > 1 else []

def _ema_alpha(series: List[float], alpha: float) -> float:
    if not series:
        return 0.0
    v = series[0]
    for x in series:
        v = alpha * x + (1.0 - alpha) * v
    return float(v)

def _stdev_safe(series: List[float]) -> float:
    if len(series) < 2:
        return 1e-9
    m = sum(series)/len(series)
    var = sum((v-m)**2 for v in series)/len(series)
    return max(1e-9, var**0.5)

def _rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(1, period+1):
        d = prices[-i] - prices[-i-1]
        if d >= 0: gains += d
        else:      losses -= d
    avg_gain = gains / period
    avg_loss = losses / period if losses != 0 else 1e-9
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

# --- מצב פנימי לריסון Confidence ולעקביות כיוון ---
_LAST_SIGNAL_TS = 0.0
_LAST_SIDE = "WAIT"
_LAST_NORM = 0.0
_CONF_EWMA = 50.0

def _apply_hysteresis(side: str, norm_score: float) -> Tuple[str, float]:
    global _LAST_SIDE, _LAST_NORM
    if _LAST_SIDE in ("UP", "DOWN") and side != _LAST_SIDE:
        if norm_score < (_LAST_NORM + CFG["HYSTERESIS"]):
            return _LAST_SIDE, _LAST_NORM
    _LAST_SIDE, _LAST_NORM = side, norm_score
    return side, norm_score

def _direction_from_score(score: float, last_prices: List[float]) -> str:
    if score > 0:  return "UP"
    if score < 0:  return "DOWN"
    if len(last_prices) >= 2 and last_prices[-1] >= last_prices[-2]:
        return "UP"
    return "DOWN"

def _robust_vol(diffs_: List[float]) -> float:
    # MAD בקירוב ל-σ: נגד קפיצות אקראיות
    if not diffs_:
        return 1e-9
    med = sorted(diffs_)[len(diffs_)//2]
    mad = sorted(abs(v - med) for v in diffs_)[len(diffs_)//2]
    return max(1e-9, 1.4826 * mad)

def compute_signal_from_prices(prices: List[float]) -> Tuple[str, int, Dict]:
    global _LAST_SIGNAL_TS, _CONF_EWMA
    now_ts = time.time()

    if not prices or len(prices) < 8:
        return "WAIT", 50, {"reason": "insufficient_data"}

    ch = _log_changes(prices)
    df = _diffs(ch)
    vol_r = _robust_vol(df)
    ema_fast = _ema_alpha(ch, CFG["ALPHA_FAST"])
    ema_slow = _ema_alpha(ch, CFG["ALPHA_SLOW"])
    ema_spread = ema_fast - ema_slow       # הפרדה בין מהיר/איטי
    trend_slope = ch[-1] - ch[0]           # נטייה מצטברת
    rsi_v = _rsi(prices, CFG["RSI_PERIOD"])

    # נורמליזציה עיקרית: raw / vol_r
    raw = 0.6*ema_spread + 0.4*trend_slope
    norm = abs(raw) / max(1e-9, vol_r)

    # ענישה למצב RSI ניטרלי (פחות edge)
    if CFG["NEUTRAL_RSI_LOW"] <= rsi_v <= CFG["NEUTRAL_RSI_HIGH"]:
        norm *= 0.75

    # guard לשוק ישנוני
    slow_market_penalty = 0.0
    if vol_r < CFG["VOL_GUARD"]:
        slow_market_penalty = 0.12

    # bias עדין לפי RSI (לא הופך צד)
    bias = 0.0
    if rsi_v >= CFG["RSI_BULL"]:
        bias += 0.05
    elif rsi_v <= CFG["RSI_BEAR"]:
        bias -= 0.05

    # הפקת כיוון
    side_pre = _direction_from_score(raw, prices)
    # היסטרזיס נגד היפוכים מהירים
    side, norm_adj = _apply_hysteresis(side_pre, norm)

    # Cooldown נגד “מרדף”
    if _LAST_SIGNAL_TS and (now_ts - _LAST_SIGNAL_TS) < CFG["COOLDOWN_SEC"]:
        if side != _LAST_SIDE and side in ("UP", "DOWN"):
            return "WAIT", 52, {"reason": "cooldown", "since_last": now_ts - _LAST_SIGNAL_TS}

    # Confidence אדפטיבי ומרוסן:
    # בסיס: 50 + 30*tanh(norm_adj) → טווח טיפוסי 55..~80 (בלי להיתקע על 86)
    conf_base = 50 + 30*math.tanh(norm_adj + bias)
    conf_base -= slow_market_penalty*100.0  # ענישה לשוק איטי
    # EWMA כדי למנוע קפיצות וריצוד; מקרב בין רגעי לגלובלי
    _CONF_EWMA = 0.65*_CONF_EWMA + 0.35*conf_base
    conf = int(max(CFG["CONF_MIN"], min(CFG["CONF_MAX"], _CONF_EWMA)))

    # אם האות חלש (גם אחרי הכל) → WAIT
    if conf < CFG["CONF_MIN"]:
        return "WAIT", conf, {
            "vol": vol_r, "rsi": rsi_v, "ema_spread": ema_spread,
            "trend_slope": trend_slope, "norm": norm_adj
        }

    _LAST_SIGNAL_TS = now_ts
    dbg = {
        "n": len(prices), "price_now": prices[-1],
        "vol": vol_r, "rsi": rsi_v, "ema_spread": ema_spread,
        "trend_slope": trend_slope, "norm": norm_adj, "expiry": CFG["EXPIRY"]
    }
    return side, conf, dbg

def decide_from_ticks(ticks_deque) -> Tuple[str, int, Dict]:
    now = time.time()
    window = [p for (ts, p) in list(ticks_deque) if now - ts <= CFG["WINDOW_SEC"]]
    if len(window) < 12:
        window = [p for (_, p) in list(ticks_deque)[-12:]]
    return compute_signal_from_prices(window)
