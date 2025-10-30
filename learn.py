# learn.py
from __future__ import annotations
import time, json, os, base64, requests
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Literal, Optional

Side = Literal["UP", "DOWN"]

# === CONFIG FROM ENV ===
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()  # e.g. "Ofirsi/pocket-bot"
GITHUB_LEARNER_PATH = os.getenv("GITHUB_LEARNER_PATH", "learner_data.json").strip()

GITHUB_API_BASE = "https://api.github.com"


@dataclass
class TradeSample:
    ts: float
    asset: str
    side: Side
    conf: int
    quality: str
    agree3: bool
    rsi: float
    ema_spread: float
    persist: float
    tick_imb: float
    align_bonus: float
    result: Optional[bool] = None  # True=✅, False=❌, None=עדיין אין פידבק


@dataclass
class LiveStats:
    quality_hits: Dict[str,int] = field(default_factory=lambda: {
        "🟩 Strong":0,
        "🟨 Medium":0,
        "🟥 Weak":0
    })
    quality_miss: Dict[str,int] = field(default_factory=lambda: {
        "🟩 Strong":0,
        "🟨 Medium":0,
        "🟥 Weak":0
    })
    agree3_hits: int = 0
    agree3_miss: int = 0

    def record(self, sample: TradeSample):
        if sample.result is None:
            return
        q = sample.quality
        hit = 1 if sample.result else 0
        miss = 1 - hit

        if q not in self.quality_hits:
            self.quality_hits[q] = 0
            self.quality_miss[q] = 0

        self.quality_hits[q] += hit
        self.quality_miss[q] += miss

        if sample.agree3:
            self.agree3_hits += hit
            self.agree3_miss += miss

    def winrate_quality(self, q: str) -> float:
        h = self.quality_hits.get(q,0)
        m = self.quality_miss.get(q,0)
        tot = h+m
        return (100.0*h/tot) if tot>0 else 0.0

    def winrate_agree3(self) -> float:
        tot = self.agree3_hits + self.agree3_miss
        return (100.0*self.agree3_hits/tot) if tot>0 else 0.0


class Learner:
    """
    שומר ומטען learner_data.json ישר מה-Repo שלך בגיטהב.
    בכל פעם שאתה מקבל סיגנל / מסמן פגיעה או החטאה,
    אנחנו שולחים commit חדש עם עדכון הקובץ.
    """

    def __init__(self):
        self.samples: List[TradeSample] = []
        self.live = LiveStats()
        self._loaded = False
        self._remote_sha: Optional[str] = None  # GitHub file SHA (בשביל עדכון קיים)

    # ----- Github helpers -----

    def _headers(self):
        if not GITHUB_TOKEN:
            raise RuntimeError("Missing GITHUB_TOKEN env")
        return {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

    def _content_url(self) -> str:
        if not GITHUB_REPO:
            raise RuntimeError("Missing GITHUB_REPO env")
        return f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/contents/{GITHUB_LEARNER_PATH}"

    def _pull_from_github(self):
        """טוען learner_data.json מהריפו. אם אין שם קובץ - מתחילים ריק."""
        try:
            r = requests.get(self._content_url(), headers=self._headers(), timeout=10)
        except Exception as e:
            print(f"[LEARNER] pull error: {e}")
            return

        if r.status_code == 404:
            print("[LEARNER] no remote learner_data yet, starting fresh")
            return

        if r.status_code != 200:
            print(f"[LEARNER] pull status {r.status_code}: {r.text}")
            return

        data = r.json()
        self._remote_sha = data.get("sha")

        encoded = data.get("content", "")
        if data.get("encoding") != "base64":
            print("[LEARNER] unexpected encoding")
            return

        try:
            decoded_bytes = base64.b64decode(encoded)
            payload = json.loads(decoded_bytes.decode("utf-8"))
        except Exception as e:
            print(f"[LEARNER] decode error: {e}")
            return

        # samples מהעבר
        raw_samples = payload.get("samples", [])
        for item in raw_samples:
            try:
                self.samples.append(TradeSample(
                    ts=item["ts"],
                    asset=item["asset"],
                    side=item["side"],
                    conf=item["conf"],
                    quality=item["quality"],
                    agree3=item["agree3"],
                    rsi=item["rsi"],
                    ema_spread=item["ema_spread"],
                    persist=item["persist"],
                    tick_imb=item["tick_imb"],
                    align_bonus=item["align_bonus"],
                    result=item.get("result", None),
                ))
            except KeyError:
                # אם חסר שדה בקובץ ישן, נדלג על הדגימה
                continue

        # live stats
        raw_live = payload.get("live", {})
        self.live.quality_hits.update(raw_live.get("quality_hits", {}))
        self.live.quality_miss.update(raw_live.get("quality_miss", {}))
        self.live.agree3_hits  = raw_live.get("agree3_hits",  self.live.agree3_hits)
        self.live.agree3_miss  = raw_live.get("agree3_miss",  self.live.agree3_miss)

    def _push_to_github(self, message: str):
        """כותב את המצב המעודכן לריפו (commit חדש)."""
        if not GITHUB_TOKEN or not GITHUB_REPO:
            print("[LEARNER] skip push (missing GitHub env)")
            return

        body = {
            "samples": [asdict(s) for s in self.samples],
            "live": {
                "quality_hits": self.live.quality_hits,
                "quality_miss": self.live.quality_miss,
                "agree3_hits": self.live.agree3_hits,
                "agree3_miss": self.live.agree3_miss,
            }
        }

        encoded_content = base64.b64encode(
            json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": message,
            "content": encoded_content,
        }
        if self._remote_sha:
            payload["sha"] = self._remote_sha

        try:
            r = requests.put(self._content_url(), headers=self._headers(), json=payload, timeout=10)
        except Exception as e:
            print(f"[LEARNER] push error: {e}")
            return

        if r.status_code not in (200,201):
            print(f"[LEARNER] push status {r.status_code}: {r.text}")
            return

        resp = r.json()
        self._remote_sha = resp.get("content", {}).get("sha", self._remote_sha)

    # ----- Persistence lifecycle -----

    def load_if_needed(self):
        if self._loaded:
            return
        self._loaded = True
        self._pull_from_github()

    def save_now(self, message: str):
        self._push_to_github(message)

    # ----- API שקורא main.py -----

    def new_sample(self,
                   asset: str,
                   side: Side,
                   conf: int,
                   quality: str,
                   agree3: bool,
                   rsi: float,
                   ema_spread: float,
                   persist: float,
                   tick_imb: float,
                   align_bonus: float) -> int:
        """
        נוצר סיגנל / כניסה אפשרית. עדיין לא ידוע אם הצליח.
        נשמר גם בגיטהב.
        """
        self.load_if_needed()
        s = TradeSample(
            ts=time.time(),
            asset=asset,
            side=side,
            conf=conf,
            quality=quality,
            agree3=agree3,
            rsi=rsi,
            ema_spread=ema_spread,
            persist=persist,
            tick_imb=tick_imb,
            align_bonus=align_bonus,
            result=None
        )
        self.samples.append(s)
        idx = len(self.samples)-1
        self.save_now(message="add new sample")
        return idx

    def mark_result(self, idx: int, success: bool):
        """
        אחרי פקיעה אתה לוחץ ✅ או ❌.
        פה נסגור את העסקה, נעדכן סטטיסטיקה, ונשמור לגיטהב.
        """
        self.load_if_needed()
        if idx < 0 or idx >= len(self.samples):
            return
        self.samples[idx].result = success
        self.live.record(self.samples[idx])
        self.save_now(message="update sample result")

    def last_open_index(self) -> Optional[int]:
        """
        אם מסיבה כלשהי פספסת ✅/❌ לעסקה קודמת, זה עוזר למצוא אותה.
        כרגע לא משתמשים בזה חיצונית, אבל נשאיר.
        """
        self.load_if_needed()
        for i in range(len(self.samples)-1, -1, -1):
            if self.samples[i].result is None:
                return i
        return None

    def summarize(self) -> Dict[str,str]:
        """
        זה מה שהבוט מדפיס לך בסטטוס (win rates).
        """
        self.load_if_needed()
        return {
            "Strong win%": f"{self.live.winrate_quality('🟩 Strong'):.1f}%",
            "Medium win%": f"{self.live.winrate_quality('🟨 Medium'):.1f}%",
            "Weak win%": f"{self.live.winrate_quality('🟥 Weak'):.1f}%",
            "Agree3 win%": f"{self.live.winrate_agree3():.1f}%",
        }

    def dynamic_thresholds(self, base_enter: int, base_aggr: int):
        """
        מתאים ספי כניסה למסחר האוטומטי לפי ביצועים היסטוריים.
        אם Strong אצלך באמת מרוויח הרבה → נוריד קצת את הרף.
        אם Medium חלש → נעלה את הסף האגרסיבי.
        """
        self.load_if_needed()

        strong_wr = self.live.winrate_quality("🟩 Strong")
        new_enter = base_enter
        if strong_wr > 70.0 and base_enter > 60:
            new_enter = max(60, base_enter - 3)

        medium_wr = self.live.winrate_quality("🟨 Medium")
        new_aggr = base_aggr
        if medium_wr < 50.0 and base_aggr < new_enter:
            new_aggr = new_enter

        return new_enter, new_aggr


# אובייקט גלובלי שמשתמשים בו ב-main
LEARNER = Learner()
