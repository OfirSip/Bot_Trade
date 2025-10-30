from __future__ import annotations
import os, json, time, base64, threading, requests
from typing import Optional, Dict, Any, List

###############################################################################
# LEARNER משופר – ללא שינוי בלוגיקה החישובית המקורית, רק ייצוב ובלמים
###############################################################################

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_LEARNER_PATH = os.getenv("GITHUB_LEARNER_PATH", "learner_data.json").strip()


# ============================================================
# GitHub helpers
# ============================================================

def _github_headers():
    if not GITHUB_TOKEN:
        return None
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PocketOptionLearnerBot"
    }

def github_load_file() -> Optional[Dict[str, Any]]:
    if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_LEARNER_PATH):
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LEARNER_PATH}"
    headers = _github_headers()
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        raw = base64.b64decode(r.json().get("content", "")).decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None

def github_save_file(payload: Dict[str, Any]) -> bool:
    if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_LEARNER_PATH):
        return False
    headers = _github_headers()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LEARNER_PATH}"
    sha = None
    try:
        info = requests.get(url, headers=headers, timeout=10)
        if info.status_code == 200:
            sha = info.json().get("sha")
    except Exception:
        pass
    body_str = json.dumps(payload, ensure_ascii=False, indent=2)
    b64_body = base64.b64encode(body_str.encode("utf-8")).decode("ascii")
    put_payload = {
        "message": f"update learner_data {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "content": b64_body,
        "branch": "main",
    }
    if sha:
        put_payload["sha"] = sha
    try:
        r = requests.put(url, headers=headers, json=put_payload, timeout=10)
        return 200 <= r.status_code < 300
    except Exception:
        return False


# ============================================================
# Learner
# ============================================================

class LearnerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples: List[Dict[str, Any]] = []
        self.threshold_enter = 70
        self.threshold_aggr = 80
        self.counter = 0

    # ---------- Persistence ----------
    def load_from_github(self):
        data = github_load_file()
        if not data:
            return
        with self.lock:
            self.samples = data.get("samples", [])
            self.threshold_enter = int(data.get("threshold_enter", self.threshold_enter))
            self.threshold_aggr = int(data.get("threshold_aggr", self.threshold_aggr))

    def save_to_github(self):
        with self.lock:
            payload = {
                "samples": self.samples[-500:],
                "threshold_enter": self.threshold_enter,
                "threshold_aggr": self.threshold_aggr,
                "last_update_ts": time.time(),
            }
        github_save_file(payload)

    # ---------- Data ----------
    def new_sample(self, asset: str, side: str, conf: int, quality: str, agree3: bool,
                   rsi: float, ema_spread: float, persist: float, tick_imb: float, align_bonus: float) -> int:
        s = {
            "ts": time.time(),
            "asset": asset,
            "side": side,
            "conf": conf,
            "quality": quality,
            "agree3": bool(agree3),
            "rsi": rsi,
            "ema_spread": ema_spread,
            "persist": persist,
            "tick_imb": tick_imb,
            "align_bonus": align_bonus,
            "result": None
        }
        with self.lock:
            self.samples.append(s)
            return len(self.samples) - 1

    def mark_result(self, idx: int, success: bool):
        with self.lock:
            if 0 <= idx < len(self.samples):
                self.samples[idx]["result"] = bool(success)
        self.save_to_github()

    # ---------- Statistics ----------
    def _collect_stats(self):
        with self.lock:
            data = list(self.samples)
        buckets = {"🟩 Strong": {"hit":0,"tot":0},
                   "🟨 Medium": {"hit":0,"tot":0},
                   "🟥 Weak": {"hit":0,"tot":0}}
        agree3 = {"hit":0,"tot":0}
        for s in data:
            res = s.get("result")
            if res is None:
                continue
            q = s.get("quality")
            if q in buckets:
                buckets[q]["tot"] += 1
                if res:
                    buckets[q]["hit"] += 1
            if s.get("agree3"):
                agree3["tot"] += 1
                if res:
                    agree3["hit"] += 1
        def pct(h,t): return (100*h/t) if t>0 else 0.0
        return {
            "strong_wr": pct(buckets["🟩 Strong"]["hit"], buckets["🟩 Strong"]["tot"]),
            "agree_wr": pct(agree3["hit"], agree3["tot"])
        }

    # ---------- Dynamic thresholds ----------
    def dynamic_thresholds(self, base_enter: int, base_aggr: int):
        stats = self._collect_stats()
        self.counter += 1
        if self.counter % 10 != 0:
            return self.threshold_enter, self.threshold_aggr
        strong_wr = stats["strong_wr"]
        agree_wr = stats["agree_wr"]
        enter = base_enter
        aggr = base_aggr
        if strong_wr >= 65: enter = max(50, base_enter - 3)
        elif strong_wr < 50: enter = min(90, base_enter + 5)
        if agree_wr >= 70: aggr = max(60, base_aggr - 5)
        elif agree_wr < 50: aggr = min(95, base_aggr + 5)
        with self.lock:
            self.threshold_enter = min(80, max(65, enter))
            self.threshold_aggr = min(90, max(75, aggr))
        self.save_to_github()
        return self.threshold_enter, self.threshold_aggr


LEARNER = LearnerState()

def init_learner_from_remote():
    LEARNER.load_from_github()
