# visuals.py
from __future__ import annotations
import time, io
from typing import Deque, Tuple, List
import matplotlib
matplotlib.use("Agg")  # כתיבה לקובץ בלי DISPLAY
import matplotlib.pyplot as plt

def make_price_figure_png(ticks: List[Tuple[float, float]], window_sec: float = 22.0) -> bytes:
    now = time.time()
    win = [(ts, p) for (ts, p) in ticks if now - ts <= window_sec]
    if len(win) < 5:
        win = ticks[-5:]
    if not win:
        buf = io.BytesIO()
        fig = plt.figure(figsize=(6,3))
        plt.title("No data yet")
        fig.tight_layout()
        fig.savefig(buf, format="png", dpi=140)
        plt.close(fig)
        return buf.getvalue()

    xs = [ts - win[0][0] for (ts, _) in win]  # סקייל לזמן יחסי
    ys = [p for (_, p) in win]

    buf = io.BytesIO()
    fig = plt.figure(figsize=(6,3))
    plt.plot(xs, ys, linewidth=2.0)  # ללא צבע ספציפי
    plt.title("Price (last ~window)")
    plt.xlabel("sec (relative)"); plt.ylabel("price")
    plt.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    return buf.getvalue()
