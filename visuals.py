# visuals.py
from __future__ import annotations
import time, io
from typing import List, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def make_overlay_figure_png(ticks: List[Tuple[float, float]], window_sec: float = 26.0) -> bytes:
    now = time.time()
    win = [(ts, p) for (ts, p) in ticks if now - ts <= window_sec]
    if len(win) < 6:
        win = ticks[-6:]
    buf = io.BytesIO()
    fig = plt.figure(figsize=(6, 3.2))

    if not win:
        plt.title("No data yet")
        plt.xlabel("time (sec)")
        plt.ylabel("price")
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=140)
        plt.close(fig)
        return buf.getvalue()

    xs = [ts - win[0][0] for (ts, _) in win]
    ys = [p for (_, p) in win]

    # Price line
    plt.plot(xs, ys, linewidth=2.0)

    # lightweight EMA overlays (no external libs): simple smoothing
    def ema(arr, span=5):
        if not arr:
            return []
        alpha = 2.0 / (span + 1.0)
        v = arr[0]
        out = []
        for a in arr:
            v = alpha * a + (1 - alpha) * v
            out.append(v)
        return out

    ema_fast = ema(ys, span=max(3, int(len(ys)*0.15)))
    ema_slow = ema(ys, span=max(5, int(len(ys)*0.35)))

    plt.plot(xs, ema_fast, linestyle="--", linewidth=1.3)
    plt.plot(xs, ema_slow, linestyle=":", linewidth=1.3)

    plt.title("Price • EMA(fast, slow) • last ~window")
    plt.xlabel("sec (relative)")
    plt.ylabel("price")
    plt.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    return buf.getvalue()
