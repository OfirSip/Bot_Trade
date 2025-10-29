# indicators.py
from __future__ import annotations
from typing import List
import math

def ema_alpha(series: List[float], alpha: float) -> float:
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
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period if losses != 0 else 1e-9
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def stdev(series: List[float]) -> float:
    if len(series) < 2:
        return 0.0
    m = sum(series) / len(series)
    var = sum((x - m) ** 2 for x in series) / len(series)
    return math.sqrt(var)

def stdev_safe(series: List[float], eps: float = 1e-9) -> float:
    s = stdev(series)
    return s if s > 0 else eps

def slope(series: List[float]) -> float:
    if not series:
        return 0.0
    return float(series[-1] - series[0])

def median(x: List[float]) -> float:
    if not x:
        return 0.0
    s = sorted(x)
    n = len(s)
    mid = n // 2
    return (s[mid] if n % 2 == 1 else 0.5 * (s[mid - 1] + s[mid]))

def mad(x: List[float]) -> float:
    """Median absolute deviation."""
    if not x:
        return 0.0
    m = median(x)
    dev = [abs(v - m) for v in x]
    return median(dev)
