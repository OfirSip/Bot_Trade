# features.py
from __future__ import annotations
import math
from typing import List, Dict
from indicators import ema_alpha, rsi, stdev_safe, slope, mad

def log_changes(prices: List[float]) -> List[float]:
    if not prices:
        return []
    base = prices[0]
    return [math.log(max(1e-12, p / base)) for p in prices]

def diffs(x: List[float]) -> List[float]:
    return [x[i] - x[i - 1] for i in range(1, len(x))] if len(x) > 1 else []

def zscore(x: List[float]) -> List[float]:
    if not x:
        return []
    m = sum(x) / len(x)
    s = stdev_safe(x)
    return [(v - m) / s for v in x]

def rolling_persistence(x: List[float]) -> float:
    """
    מדד התמדה כיוונית: אחוז צעדים עם אותו סימן כמו האחרון.
    מלחם סיגנל שקרי: אם אין עקביות – נוריד confidence.
    """
    if len(x) < 5:
        return 0.5
    last_sign = 1 if x[-1] >= 0 else -1
    same = sum(1 for v in x if (1 if v >= 0 else -1) == last_sign)
    return same / len(x)

def robust_vol(diffs_: List[float]) -> float:
    """
    תנודתיות חסינת חריגים: MAD בקירוב ל-σ (≈1.4826*MAD).
    מונע "הפתעות" מטיק בודד קופצני.
    """
    return max(1e-9, 1.4826 * mad(diffs_))

def ema_pair_spread(changes: List[float], alpha_fast: float, alpha_slow: float) -> float:
    return ema_alpha(changes, alpha_fast) - ema_alpha(changes, alpha_slow)

def normalize_score(score: float, vol: float) -> float:
    return abs(score) / max(1e-12, vol)

def direction_from_score(score: float, last_prices: List[float]) -> str:
    if score > 0:
        return "UP"
    if score < 0:
        return "DOWN"
    if len(last_prices) >= 2 and last_prices[-1] >= last_prices[-2]:
        return "UP"
    return "DOWN"

def regime_classifier(prices: List[float], diffs_: List[float]) -> str:
    """
    רג'ים בסיסי:
    - TREND: שיפוע לוגי מצטבר בולט + התמדה גבוהה + תנודתיות לא-אפסית
    - RANGE: שיפוע קטן/מתחלף, התמדה נמוכה
    - SHOCK: תנודתיות חריגה מאוד (MAD גבוה) — לצמצם אמון אם אין כיוון יציב
    """
    ch = log_changes(prices)
    sl = slope(ch)
    vol_r = robust_vol(diffs_)
    pers = rolling_persistence(diffs_)
    if vol_r > 3e-3 and abs(sl) < 1e-3:
        return "SHOCK"
    if abs(sl) > 6e-4 and pers >= 0.6:
        return "TREND"
    return "RANGE"
