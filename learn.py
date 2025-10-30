# learn.py
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

Side = Literal["UP", "DOWN"]

@dataclass
class TradeSample:
    ts: float
    asset: str
    side: Side
    conf: int
    quality: str
    agree3: bool           # האם שלושת הטווחים הסכימו
    rsi: float
    ema_spread: float
    persist: float
    tick_imb: float
    align_bonus: float
    result: Optional[bool] = None  # True=✅, False=❌, None=עדיין לא דווח

@dataclass
class LiveStats:
    # win/loss לכל איכות
    quality_hits: Dict[str,int] = field(default_factory=lambda: {"🟩 Strong":0,"🟨 Medium":0,"🟥 Weak":0})
    quality_miss: Dict[str,int] = field(default_factory=lambda: {"🟩 Strong":0,"🟨 Medium":0,"🟥 Weak":0})
    # win/loss כשיש הסכמה מלאה בשלושה טווחים
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
    אוסף טריידים, מעדכן סטטיסטיקה, ומאפשר התאמת thresholds.
    כרגע בזיכרון RAM.
    אפשר בעתיד לשפוך ל-JSON בדיסק.
    """
    def __init__(self):
        self.samples: List[TradeSample] = []
        self.live = LiveStats()

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
        return len(self.samples)-1  # מחזיר אינדקס של הדגימה

    def mark_result(self, idx: int, success: bool):
        if idx < 0 or idx >= len(self.samples):
            return
        self.samples[idx].result = success
        self.live.record(self.samples[idx])

    def last_open_index(self) -> Optional[int]:
        # תחזיר את האינדקס האחרון שעדיין לא קיבל ✅/❌
        for i in range(len(self.samples)-1, -1, -1):
            if self.samples[i].result is None:
                return i
        return None

    def summarize(self) -> Dict[str,str]:
        return {
            "Strong win%": f"{self.live.winrate_quality('🟩 Strong'):.1f}%",
            "Medium win%": f"{self.live.winrate_quality('🟨 Medium'):.1f}%",
            "Weak win%": f"{self.live.winrate_quality('🟥 Weak'):.1f}%",
            "Agree3 win%": f"{self.live.winrate_agree3():.1f}%",
        }

    def dynamic_thresholds(self, base_enter: int, base_aggr: int):
        """
        ים של קסם:
        אם Strong באמת מצליח אצלך מאוד, נקל עליו קצת (נוריד רף).
        אם הוא לא מצליח - נעלה רף.

        זאת התאמה מקומית, לא "למידת מכונה", אבל זה צעד חכם קדימה.
        """
        strong_wr = self.live.winrate_quality("🟩 Strong")
        # יעד: אם Strong>70%, אפשר לרדת קצת בסף הכניסה, עד מינימום 60.
        adj_enter = base_enter
        if strong_wr > 70.0 and base_enter > 60:
            adj_enter = max(60, base_enter - 3)

        # אם Medium גרוע, נעלה את הסף ה"אגרסיבי"
        medium_wr = self.live.winrate_quality("🟨 Medium")
        adj_aggr = base_aggr
        if medium_wr < 50.0 and base_aggr < adj_enter:
            # אם מדיום גרוע, אל תכניס אגרסיבי נמוך מידי
            adj_aggr = adj_enter

        return adj_enter, adj_aggr

# אובייקט גלובלי שנייבא ב-main
LEARNER = Learner()
