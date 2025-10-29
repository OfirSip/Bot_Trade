# strategy.py
from __future__ import annotations
import math, time
from typing import Tuple, Dict, List

CFG = {
    "WINDOW_SEC": 26.0,      # מתעדכן מהבוט
    "ALPHA_FAST": 0.40,
    "ALPHA_SLOW": 0.14,
    "RSI_PERIOD": 14,
    "RSI_BULL": 55.0,
    "RSI_BEAR": 45.0,
    "CONF_MIN": 55,
    "CONF_MAX": 96,
    "VOL_GUARD": 8e-5,
    "HYSTERESIS": 0.08,
    "COOLDOWN_SEC": 12.0,
    "NEUTRAL_RSI_LOW": 48.0,
    "NEUTRAL_RSI_HIGH": 52.0,
    "EXPIRY": "M1",
}

# ===== עזרי חישוב =====
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

def _robust_vol(diffs_: List[float]) -> float:
    if not diffs_:
        return 1e-9
    s = sorted(diffs_)
    med = s[len(s)//2]
    mad = sorted(abs(v - med) for v in diffs_)[len(diffs_)//2]
    return max(1e-9, 1.4826 * mad)

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

def _direction_from_score(score: float, last_prices: List[float]) -> str:
    if score > 0:  return "UP"
    if score < 0:  return "DOWN"
    if len(last_prices) >= 2 and last_prices[-1] >= last_prices[-2]:
        return "UP"
    return "DOWN"

def _persistence_ratio(step_series: List[float]) -> float:
    if not step_series:
        return 0.5
    pos = sum(1 for d in step_series if d >= 0)
    return pos / len(step_series)

def _breakout_flags(prices: list[float]) -> tuple[bool, bool]:
    if len(prices) < 6:
        return (False, False)
    hi = max(prices[:-1])
    lo = min(prices[:-1])
    last = prices[-1]
    return (last > hi, last < lo)

# ===== מצב פנימי =====
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

def compute_signal_from_prices(prices: List[float]) -> Tuple[str, int, Dict]:
    global _LAST_SIGNAL_TS, _CONF_EWMA
    now_ts = time.time()

    if not prices or len(prices) < 10:
        return "WAIT", 50, {"reason": "insufficient_data"}

    ch  = _log_changes(prices)
    df  = _diffs(ch)
    vol = _robust_vol(df)
    ema_fast  = _ema_alpha(ch, CFG["ALPHA_FAST"])
    ema_slow  = _ema_alpha(ch, CFG["ALPHA_SLOW"])
    ema_spread = ema_fast - ema_slow
    trend_slope = ch[-1] - ch[0]
    rsi_v = _rsi(prices, CFG["RSI_PERIOD"])

    raw  = 0.58 * ema_spread + 0.42 * trend_slope
    norm = abs(raw) / max(1e-9, vol)

    side_pre = _direction_from_score(raw, prices)
    side, norm_adj = _apply_hysteresis(side_pre, norm)

    # עונשים “רכים”
    if CFG["NEUTRAL_RSI_LOW"] <= rsi_v <= CFG["NEUTRAL_RSI_HIGH"]:
        norm_adj *= 0.75
    if vol < CFG["VOL_GUARD"]:
        norm_adj *= 0.85

    # ===== מגבר יישור (alignment) =====
    long_win_n   = max(20, int(round(len(prices) * 2.5)))
    long_prices  = prices[-long_win_n:] if len(prices) >= long_win_n else prices
    chL  = _log_changes(long_prices)
    dfL  = _diffs(chL)
    ema_spread_L = _ema_alpha(chL, CFG["ALPHA_FAST"]) - _ema_alpha(chL, CFG["ALPHA_SLOW"])
    slope_L      = chL[-1] - chL[0]
    side_long    = _direction_from_score(0.58*ema_spread_L + 0.42*slope_L, long_prices)

    bo_up, bo_dn = _breakout_flags(prices)
    breakout_ok  = (bo_up and side == "UP") or (bo_dn and side == "DOWN")

    persist_price = _persistence_ratio(_diffs(prices))  # על מחיר ישיר לרגישות צד
    tick_imbalance = abs(2*persist_price - 1.0)         # 0..1, 0.36 ≈ 68%

    rsi_support = (side == "UP" and rsi_v >= max(58.0, CFG["RSI_BULL"])) or \
                  (side == "DOWN" and rsi_v <= min(42.0, CFG["RSI_BEAR"]))

    alignment_bonus = 0.0
    if side == side_long and rsi_support:
        alignment_bonus += 0.12
    if breakout_ok:
        alignment_bonus += 0.10
    if tick_imbalance >= 0.36:
        alignment_bonus += 0.06

    # בסיס בטחון
    conf_base = 50 + 30 * math.tanh(norm_adj)
    conf_base += alignment_bonus * 100.0  # עד ~+12 נק'

    # ריכוך EWMA
    _CONF_EWMA = 0.6*_CONF_EWMA + 0.4*conf_base
    conf = int(max(CFG["CONF_MIN"], min(CFG["CONF_MAX"], _CONF_EWMA)))

    # Cooldown: מניעת היפוך מיידי
    if _LAST_SIGNAL_TS and (now_ts - _LAST_SIGNAL_TS) < CFG["COOLDOWN_SEC"]:
        if side != _LAST_SIDE and side in ("UP","DOWN"):
            return "WAIT", max(52, CFG["CONF_MIN"]-3), {"reason":"cooldown"}

    if conf < CFG["CONF_MIN"]:
        return "WAIT", conf, {
            "vol": vol, "rsi": rsi_v, "ema_spread": ema_spread,
            "trend_slope": trend_slope, "norm": norm_adj,
            "persist": persist_price, "tick_imb": tick_imbalance,
            "align_bonus": alignment_bonus
        }

    _LAST_SIGNAL_TS = now_ts
    dbg = {
        "n": len(prices),
        "price_now": prices[-1],
        "vol": vol, "rsi": rsi_v, "ema_spread": ema_spread, "trend_slope": trend_slope,
        "norm": norm_adj, "persist": persist_price, "tick_imb": tick_imbalance,
        "align_bonus": alignment_bonus, "expiry": CFG["EXPIRY"]
    }
    return side, conf, dbg

def decide_from_ticks(ticks_deque) -> Tuple[str, int, Dict]:
    now = time.time()
    window = [p for (ts, p) in list(ticks_deque) if now - ts <= CFG["WINDOW_SEC"]]
    if len(window) < 12:
        window = [p for (_, p) in list(ticks_deque)[-12:]]
    return compute_signal_from_prices(window)
