# indicators.py
from __future__ import annotations
from typing import List
import math

def ema_alpha(series: List[float], alpha: float) -> float:
    """EMA לפי אלפא ישיר (0..1)."""
    if not series:
        return 0.0
    v = series[0]
    for x in series:
        v = alpha * x + (1.0 - alpha) * v
    return float(v)

def rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff >= 0: gains += diff
        else:         losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period if losses != 0 else 1e-9
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def simple_vol(diffs: List[float]) -> float:
    """סטטיות חישובית (סטיית תקן פשוטה). לא 0 לעולם."""
    if len(diffs) < 2:
        return 1e-9
    m = sum(diffs) / len(diffs)
    var = sum((x - m) ** 2 for x in diffs) / len(diffs)
    s = math.sqrt(var)
    return s if s > 0 else 1e-9

def slope(series: List[float]) -> float:
    if not series:
        return 0.0
    return float(series[-1] - series[0])
