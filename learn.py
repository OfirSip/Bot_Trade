# learn.py
from __future__ import annotations
import os, json, time, base64, threading, requests
from typing import Optional, Dict, Any, List

###############################################################################
# מבוא
# -----
# LEARNER אוסף דגימות (סיגנלים), מקבל ממך פידבק ✅/❌,
# מחשב סטטיסטיקות הצלחה לפי איכות (Strong/Medium/Weak, וגם לפי "Agree3TF"),
# ומפיק thresholds חדשים למסחר אוטומטי.
#
# שדרוג עכשיו:
# - זיכרון מתמשך בין ריצות דרך GitHub.
#   הבוט טוען היסטוריה בתחילה ושומר חזרה אחרי כל עדכון תוצאה.
###############################################################################


# ============================================================
# ENV
# ============================================================

GITHUB_TOKEN          = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO           = os.getenv("GITHUB_REPO", "").strip()            # "username/reponame"
GITHUB_LEARNER_PATH   = os.getenv("GITHUB_LEARNER_PATH", "learner_data.json").strip()

# לדוגמה:
# GITHUB_TOKEN=ghp_abc123...
# GITHUB_REPO="Ofirsi/po-bot"
# GITHUB_LEARNER_PATH="learner_data.json"


# ============================================================
# Helper: GitHub storage
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
    """
    מוריד את הקובץ JSON מהריפו (אם קיים) ומחזיר dict.
    אם אין הרשאות או אין קובץ -> מחזיר None.
    """
    if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_LEARNER_PATH):
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LEARNER_PATH}"
    headers = _github_headers()
    if headers is None:
        return None

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # GitHub מחזיק את התוכן ב-base64
            b64 = data.get("content", "")
            raw = base64.b64decode(b64).decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        else:
            # file not found or no access
            return None
    except Exception:
        return None

def github_save_file(payload: Dict[str, Any]) -> bool:
    """
    שומר את ה-data לריפו בנתיב GITHUB_LEARNER_PATH.
    אם הקובץ כבר קיים -> צריך להביא גם את ה-SHA כדי לעדכן (PUT).
    אם אין קובץ -> ניצור חדש.
    מחזיר True אם הצליח.
    """
    if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_LEARNER_PATH):
        return False

    headers = _github_headers()
    if headers is None:
        return False

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_LEARNER_PATH}"

    # לפני שאנחנו שומרים, נבדוק אם הקובץ כבר קיים כדי להשיג sha
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
        "branch": "main",   # אם הריפו שלך לא על main אלא על master תשנה פה
    }
    if sha is not None:
        put_payload["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=put_payload, timeout=10)
        return (200 <= r.status_code < 300)
    except Exception:
        return False


# ============================================================
# Learner State
# ============================================================

class LearnerState:
    """
    אנחנו מחזיקים:
    - samples: רשימת דגימות (סיגנלים) שקרו.
      כל איבר:
        {
          "ts": timestamp,
          "asset": "EUR/USD",
          "side": "UP"/"DOWN",
          "conf": 73,
          "quality": "🟩 Strong" / "🟨 Medium" / "🟥 Weak",
          "agree3": True/False,
          "rsi": float,
          "ema_spread": float,
          "persist": float,
          "tick_imb": float,
          "align_bonus": float,
          "result": None/True/False
        }

    - stats_by_quality: נסיק מתוך samples את האחוזי פגיעה לפי איכות
    - stats_agree3: כמה אחוז הצלחה כשיש הסכמה בכל הטיימפריימים
    - thresholds למסחר אוטומטי:
        threshold_enter  (כמה ביטחון צריך כדי להיכנס בכלל)
        threshold_aggr   (כמה ביטחון כדי להיכנס באגרסיביות)
    """

    def __init__(self):
        self.lock = threading.Lock()

        self.samples: List[Dict[str, Any]] = []
        # ערכי ברירת מחדל אם אין דאטה עדיין:
        self.threshold_enter: int = 70
        self.threshold_aggr:  int = 80

    # ---------- Persistence to/from GitHub ----------

    def load_from_github(self):
        """
        נקרא פעם אחת כשהבוט עולה.
        מנסה למשוך היסטוריה קיימת מהריפו.
        """
        data = github_load_file()
        if not data:
            return

        with self.lock:
            # samples
            incoming_samples = data.get("samples", [])
            if isinstance(incoming_samples, list):
                self.samples = incoming_samples

            # thresholds
            th_enter = data.get("threshold_enter")
            th_aggr  = data.get("threshold_aggr")
            if isinstance(th_enter, (int,float)):
                self.threshold_enter = int(th_enter)
            if isinstance(th_aggr, (int,float)):
                self.threshold_aggr  = int(th_aggr)

    def save_to_github(self):
        """
        שומר snapshot עדכני לריפו (async-safe בתוך lock).
        נקרא אחרי עדכון תוצאה או כשמשנים thresholds.
        """
        if not (GITHUB_TOKEN and GITHUB_REPO and GITHUB_LEARNER_PATH):
            return  # אין קונפיג, אז לא ננסה בכלל

        with self.lock:
            payload = {
                "samples": self.samples,
                "threshold_enter": self.threshold_enter,
                "threshold_aggr": self.threshold_aggr,
                "last_update_ts": time.time(),
            }
        github_save_file(payload)

    # ---------- Recording new samples ----------

    def new_sample(
        self,
        asset: str,
        side: str,
        conf: int,
        quality: str,
        agree3: bool,
        rsi: float,
        ema_spread: float,
        persist: float,
        tick_imb: float,
        align_bonus: float
    ) -> int:
        """
        מוסיף סיגנל חדש (לפני שאתה יודע אם הצליח או לא).
        מחזיר אינדקס שלו כדי שנוכל לעדכן תוצאה אחר כך.
        """
        sample = {
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
            "result": None,  # יתעדכן ל-True/False אחרי שתדווח ✅/❌
        }

        with self.lock:
            self.samples.append(sample)
            idx = len(self.samples) - 1

        return idx

    def mark_result(self, idx: int, success: bool):
        """
        משתמש לוחץ '✅ פגיעה' או '❌ החטאה'.
        זה קובע אם הסיגנל האחרון עבד בפועל.
        ואז נשמור לגיטהאב.
        """
        with self.lock:
            if 0 <= idx < len(self.samples):
                self.samples[idx]["result"] = bool(success)

        # נשמור snapshot מעודכן
        self.save_to_github()

    # ---------- Stats / summary ----------

    def _collect_stats(self):
        """
        מחשב אחוזי פגיעה לפי quality ו-agree3.
        """
        with self.lock:
            data = list(self.samples)

        # לפי איכות
        buckets = {
            "🟩 Strong": {"hit":0,"tot":0},
            "🟨 Medium": {"hit":0,"tot":0},
            "🟥 Weak":   {"hit":0,"tot":0},
        }
        # לפי agree3
        agree3_stats = {"hit":0,"tot":0}

        for s in data:
            res = s.get("result", None)
            qual = s.get("quality","?")
            agr  = bool(s.get("agree3", False))

            if qual in buckets and res is not None:
                buckets[qual]["tot"] += 1
                if res:
                    buckets[qual]["hit"] += 1

            if agr and res is not None:
                agree3_stats["tot"] += 1
                if res:
                    agree3_stats["hit"] += 1

        def pct(h,t):
            return (100.0*h/t) if t>0 else 0.0

        strong_wr = pct(buckets["🟩 Strong"]["hit"], buckets["🟩 Strong"]["tot"])
        med_wr    = pct(buckets["🟨 Medium"]["hit"], buckets["🟨 Medium"]["tot"])
        weak_wr   = pct(buckets["🟥 Weak"]["hit"],   buckets["🟥 Weak"]["tot"])
        agree_wr  = pct(agree3_stats["hit"], agree3_stats["tot"])

        return {
            "Strong win%": f"{strong_wr:.1f}%",
            "Medium win%": f"{med_wr:.1f}%",
            "Weak win%": f"{weak_wr:.1f}%",
            "Agree3 win%": f"{agree_wr:.1f}%",
            "raw": {
                "strong": buckets["🟩 Strong"],
                "medium": buckets["🟨 Medium"],
                "weak":   buckets["🟥 Weak"],
                "agree3": agree3_stats,
            }
        }

    def summarize(self) -> Dict[str,str]:
        """
        משמש את הפקודה '🛰️ סטטוס' כדי להראות לך את אחוזי הפגיעה האמיתיים עד עכשיו.
        """
        stats = self._collect_stats()
        return {
            "Strong win%": stats["Strong win%"],
            "Medium win%": stats["Medium win%"],
            "Weak win%": stats["Weak win%"],
            "Agree3 win%": stats["Agree3 win%"],
        }

    # ---------- Dynamic thresholds ----------

    def dynamic_thresholds(self, base_enter: int, base_aggr: int) -> (int,int):
        """
        משתמשים בהיסטוריה שלך כדי לעדכן ספים למסחר אוטומטי.
        רעיון:
        - אם Strong ניצחונות גבוהים → אולי אפשר להוריד קצת threshold_enter
        - אם Strong גרוע לאחרונה → להעלות threshold_enter
        - אם Agree3 חזק בטירוף → אפשר להיות אגרסיבי יותר
        """
        stats = self._collect_stats()
        raw = stats["raw"]

        strong_tot = raw["strong"]["tot"]
        strong_hit = raw["strong"]["hit"]
        strong_wr  = (100.0*strong_hit/strong_tot) if strong_tot>0 else None

        agree_tot = raw["agree3"]["tot"]
        agree_hit = raw["agree3"]["hit"]
        agree_wr  = (100.0*agree_hit/agree_tot) if agree_tot>0 else None

        new_enter = base_enter
        new_aggr  = base_aggr

        # אם ה"Strong" שלך באמת חזק >60% הצלחה => אפשר טיפה להקל
        if strong_wr is not None:
            if strong_wr >= 65.0:
                new_enter = max(50, base_enter - 3)
            elif strong_wr < 50.0:
                new_enter = min(90, base_enter + 5)

        # אם יש הסכמה בין כל הטיימפריימים והיא מצליחה מאוד,
        # אפשר להיות יותר אגרסיביים כשהביטחון גבוה.
        if agree_wr is not None:
            if agree_wr >= 70.0:
                new_aggr = max(60, base_aggr - 5)
            elif agree_wr < 50.0:
                new_aggr = min(95, base_aggr + 5)

        # נשמור את הספים החדשים פנימית (כדי שגם יישמרו ל-GitHub)
        with self.lock:
            self.threshold_enter = new_enter
            self.threshold_aggr  = new_aggr

        # וגם נשמור החוצה כדי שהמידע הזה ישרוד ריסטארט
        self.save_to_github()

        return new_enter, new_aggr


# ============================================================
# אינסטנס הגלובלי שהקוד הראשי משתמש בו
# ============================================================
LEARNER = LearnerState()


# ============================================================
# פונקציה לעדכן את ה-LEARNER בתחילת הבוט
# (תקרא לזה מ-main.py בהפעלה)
# ============================================================
def init_learner_from_remote():
    """
    לקרוא בתחילת main():
      from learn import init_learner_from_remote
      init_learner_from_remote()

    זה יטען היסטוריה קיימת מ-GitHub (אם יש הרשאות ו/או אם הקובץ קיים),
    ואז ה־LEARNER ירוץ כבר עם ניסיון עבר.
    """
    LEARNER.load_from_github()
