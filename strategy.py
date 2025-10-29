# strategy.py
from __future__ import annotations
import math, time
from typing import Tuple, Dict, List
from indicators import rsi, stdev_safe
from features import (
    log_changes, diffs, robust_vol, ema_pair_spread, normalize_score,
    direction_from_score, regime_classifier, rolling_persistence
)

# פרמטרים ניתנים לשינוי מהבוט
CFG = {
    "WINDOW_SEC": 26.0,     # חלון מעט גדול יותר להפחתת רעש
    "ALPHA_FAST": 0.40,     # EMA מהיר
    "ALPHA_SLOW": 0.14,     # EMA איטי
    "RSI_PERIOD": 14,
    "RSI_BULL": 55.0,       # bias LONG
    "RSI_BEAR": 45.0,       # bias SHORT
    "CONF_MIN": 60,         # סף אמון מינימלי להגשה
    "CONF_MAX": 96,         # תקרה
    "VOL_GUARD": 8e-5,      # אם מתחת — שוק "ישנוני", נוריד אמון
    "HYSTERESIS": 0.07,     # רצועת היסטרזיס: כדי לא להפוך כיוון מהר
    "COOLDOWN_SEC": 12.0,   # לא להוציא שני סיגנלים סותרים מהר
    "EXPIRY": "M1",
}

_LAST_SIGNAL_TS = 0.0
_LAST_SIDE = "WAIT"
_LAST_NORM = 0.0

def _apply_hysteresis(side: str, norm_score: float) -> Tuple[str, float]:
    global _LAST_SIDE, _LAST_NORM
    # אם כיוון מתחלף אבל העוצמה לא חצתה רצועה — שמור על הכיוון הקודם
    if _LAST_SIDE in ("UP", "DOWN") and side != _LAST_SIDE:
        band = CFG["HYSTERESIS"]
        if norm_score < (_LAST_NORM + band):
            return _LAST_SIDE, _LAST_NORM
    _LAST_SIDE, _LAST_NORM = side, norm_score
    return side, norm_score

def compute_signal_from_prices(prices: List[float]) -> Tuple[str, int, Dict]:
    global _LAST_SIGNAL_TS
    now_ts = time.time()

    if not prices or len(prices) < 8:
        return "WAIT", 50, {"reason": "insufficient_data"}

    ch = log_changes(prices)
    df = diffs(ch)
    vol_r = robust_vol(df)
    ema_spread = ema_pair_spread(ch, CFG["ALPHA_FAST"], CFG["ALPHA_SLOW"])
    trend_slope = ch[-1] - ch[0]
    pers = rolling_persistence(df)
    rsi_v = rsi(prices, CFG["RSI_PERIOD"])
    reg = regime_classifier(prices, df)

    # raw score: הפרדת EMA + משקל לשיפוע + עקביות
    raw = 0.55 * ema_spread + 0.35 * trend_slope + 0.10 * (pers - 0.5)
    norm = normalize_score(raw, vol_r)

    # bias לפי RSI (מוסיף ביטחון, לא הופך כיוון)
    bias = 0.0
    if rsi_v >= CFG["RSI_BULL"]:
        bias += 0.06
    elif rsi_v <= CFG["RSI_BEAR"]:
        bias -= 0.06

    # guard לשוק איטי מאוד
    conf_f = 50 + 42 * math.tanh(norm + bias)
    if vol_r < CFG["VOL_GUARD"]:
        conf_f -= 6.0

    # ברג'ים SHOCK נעניש אם אין עקביות (pers נמוך)
    if reg == "SHOCK" and pers < 0.55:
        conf_f -= 5.0

    # היסטרזיס (נגד ויפסו): אם החלפת צד בלי עוצמה מספקת — שמור על הצד הקודם
    side_pre = direction_from_score(raw, prices)
    side, norm_adj = _apply_hysteresis(side_pre, norm)

    # Cooldown: אם היה סיגנל לפני רגע (והצד מתחלף), בקש WAIT
    if _LAST_SIGNAL_TS and (now_ts - _LAST_SIGNAL_TS) < CFG["COOLDOWN_SEC"]:
        if side != _LAST_SIDE and side in ("UP", "DOWN"):
            return "WAIT", int(max(CFG["CONF_MIN"] - 5, 50)), {
                "reason": "cooldown", "since_last": now_ts - _LAST_SIGNAL_TS
            }

    conf = int(max(CFG["CONF_MIN"], min(CFG["CONF_MAX"], conf_f)))

    # אם אחרי הכל האמון עדיין נמוך מערך מינ', החזר WAIT (עדיף לא לירות)
    if conf < CFG["CONF_MIN"]:
        return "WAIT", conf, {
            "vol": vol_r, "rsi": rsi_v, "ema_spread": ema_spread,
            "trend_slope": trend_slope, "norm": norm_adj, "regime": reg, "pers": pers,
            "reason": "below_conf_min"
        }

    _LAST_SIGNAL_TS = now_ts
    dbg = {
        "n": len(prices), "price_now": prices[-1], "price_min": min(prices), "price_max": max(prices),
        "vol": vol_r, "rsi": rsi_v, "ema_spread": ema_spread, "trend_slope": trend_slope,
        "norm": norm_adj, "regime": reg, "pers": pers, "expiry": CFG["EXPIRY"]
    }
    return side, conf, dbg

def decide_from_ticks(ticks_deque) -> Tuple[str, int, Dict]:
    now = time.time()
    window = [p for (ts, p) in list(ticks_deque) if now - ts <= CFG["WINDOW_SEC"]]
    if len(window) < 12:
        window = [p for (_, p) in list(ticks_deque)[-12:]]
    return compute_signal_from_prices(window)
