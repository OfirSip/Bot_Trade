# auto_trader.py
from __future__ import annotations
import os, time, traceback
from dataclasses import dataclass, field
from typing import Optional

# Selenium / Chrome DevTools connection
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


# =====================================================================================
# קונפיג מהסביבה
# =====================================================================================

# היכן כרום שרץ במצב remote-debugging
# אם הבוט והכרום באותו מחשב: 127.0.0.1 ופורט 9222 זה טוב.
# אם הבוט בריילווי ואתה חושף טאנל מהבית -> תגדיר פה IP/DNS ופורט של הטאנל.
DEBUG_CHROME_HOST = os.getenv("DEBUG_CHROME_HOST", "127.0.0.1").strip()
DEBUG_CHROME_PORT = int(os.getenv("DEBUG_CHROME_PORT", "9222").strip())

# כמה זמן מינימום (שניות) בין עסקאות אוטומטיות רצופות
DEFAULT_MIN_INTERVAL_SEC = int(os.getenv("AUTO_MIN_INTERVAL_SEC", "15").strip())

# ספי ביטחון (יתעדכנו דינמית ע"י ה-LEARNER)
DEFAULT_THRESHOLD_ENTER = int(os.getenv("AUTO_THRESHOLD_ENTER", "70").strip())
DEFAULT_THRESHOLD_AGGR  = int(os.getenv("AUTO_THRESHOLD_AGGR", "80").strip())

# XPaths של הכפתורים בפוקט אופשן
# אלה הגיעו ממך. אם ה-HTML משתנה בפוקט, תעדכן פה.
XPATH_UP = "//div[contains(@class,'action-high-low') and contains(@class,'button-call-wrap')]//a[contains(@class,'btn') and contains(@class,'btn-call')]"
XPATH_DOWN = "//div[contains(@class,'action-high-low') and contains(@class,'button-put-wrap')]//a[contains(@class,'btn') and contains(@class,'btn-put')]"


# =====================================================================================
# מצב פנימי של המסחר האוטומטי
# =====================================================================================

@dataclass
class AutoState:
    enabled: bool = False                        # האם מסחר אוטומטי פעיל כרגע
    threshold_enter: int = DEFAULT_THRESHOLD_ENTER  # מינימום ביטחון כדי בכלל לשקול כניסה
    threshold_aggr: int = DEFAULT_THRESHOLD_AGGR   # סף "אגרסיבי" (בדרך כלל קצת יותר גבוה)
    min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC

    last_action: Optional[str] = None            # "BUY↑" / "SELL↓" / "SKIP" / "MANUAL BUY↑"
    last_action_ts: float = 0.0                  # מתי ביצענו טרייד אחרון בפועל
    last_error: Optional[str] = None             # לשמירת שגיאה פנימית אחרונה (debug)


class AutoTrader:
    """
    אחראי על:
    - חיבור ל-Chrome פתוח שכבר מחובר ל-Pocket Option.
    - לחיצה על הכפתור BUY או SELL.
    - מניעת ספאם (מרווח זמן בין טריידים).
    - כיבוד ספי ביטחון (confidence).
    """

    def __init__(self):
        self.state = AutoState()
        self._driver: Optional[webdriver.Chrome] = None

    # ------------------------------------------------------------------
    # Public API שה-main.py משתמש בו
    # ------------------------------------------------------------------

    def enable(self):
        self.state.enabled = True

    def disable(self):
        self.state.enabled = False

    def set_threshold_enter(self, val: int):
        self.state.threshold_enter = max(1, min(99, int(val)))

    def set_threshold_aggr(self, val: int):
        self.state.threshold_aggr = max(1, min(99, int(val)))

    def set_min_interval(self, seconds: int):
        self.state.min_interval_sec = max(1, int(seconds))

    def status_lines(self):
        """
        מחזיר שורות טקסט למצב האוטומציה (משמש בסטטוס בטלגרם).
        """
        lines = [
            f"AutoTrading: {'ON' if self.state.enabled else 'OFF'}",
            f"Threshold Enter: ≥{self.state.threshold_enter}",
            f"Threshold Aggressive: ≥{self.state.threshold_aggr}",
            f"Min Interval: {self.state.min_interval_sec}s",
            f"Last Action: {self.state.last_action or 'None'}",
            f"Last Action Age: {int(time.time() - self.state.last_action_ts)}s ago" if self.state.last_action_ts>0 else "Last Action Age: n/a",
            f"Chrome Target: {DEBUG_CHROME_HOST}:{DEBUG_CHROME_PORT}",
        ]
        if self.state.last_error:
            lines.append(f"Last Error: {self.state.last_error}")
        return lines

    def place_if_allowed(self, side: str, conf: int, strong_ok: bool) -> bool:
        """
        מנסה לבצע טרייד אוטומטי לפי סיגנל.
        החזרה היא True אם באמת בוצעה לחיצה BUY/SELL.
        תנאים:
        - האוטומציה דולקת
        - הכיוון הוא "UP" או "DOWN"
        - conf עומד בספים
        - עבר מספיק זמן מהעסקה הקודמת
        side: "UP" / "DOWN"
        conf: ביטחון (אחוזים)
        strong_ok: האם הבוט העריך שזה איתות איכותי (🟩 Strong + הסכמה בטיימפריימים)
        """
        if not self.state.enabled:
            self._remember("SKIP", "Auto disabled")
            return False

        # דרישת ביטחון:
        # אם זה strong_ok, אפשר להסתפק ב-threshold_enter
        # אחרת נבקש threshold_aggr
        required = self.state.threshold_enter if strong_ok else self.state.threshold_aggr
        if conf < required:
            self._remember("SKIP", f"conf {conf} < required {required}")
            return False

        # מניעת ספאם:
        now = time.time()
        if now - self.state.last_action_ts < self.state.min_interval_sec:
            self._remember("SKIP", "cooldown/min_interval")
            return False

        # בחר XPath
        if side == "UP":
            xpath = XPATH_UP
            label = "BUY↑"
        elif side == "DOWN":
            xpath = XPATH_DOWN
            label = "SELL↓"
        else:
            self._remember("SKIP", f"unsupported side {side}")
            return False

        ok = self._click_xpath(xpath)
        if ok:
            self._remember(label, None)
        else:
            self._remember("SKIP", "failed click")

        return ok

    # ================================================================
    # שדרוג: פונקציות ללחיצה ידנית מהבוט
    # ================================================================
    def manual_click_up(self) -> bool:
        """
        כופה לחיצה על UP (ידני).
        עוקף את כל הבדיקות.
        """
        ok = self._click_xpath(XPATH_UP)
        if ok:
            self._remember("MANUAL BUY↑", None)
        else:
            self._remember("MANUAL BUY↑", "failed click")
        return ok

    def manual_click_down(self) -> bool:
        """
        כופה לחיצה על DOWN (ידני).
        עוקף את כל הבדיקות.
        """
        ok = self._click_xpath(XPATH_DOWN)
        if ok:
            self._remember("MANUAL SELL↓", None)
        else:
            self._remember("MANUAL SELL↓", "failed click")
        return ok

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _remember(self, action: str, err: Optional[str]):
        self.state.last_action = action
        self.state.last_action_ts = time.time()
        self.state.last_error = err

    def _connect_driver_if_needed(self) -> bool:
        """
        מחבר self._driver לכרום שרץ כבר עם remote-debugging-port.
        אם כבר מחובר, יחזיר True.
        אם לא מצליח להתחבר -> False.
        """

        # כבר יש חיבור פעיל? ננסה להשתמש בו
        if self._driver is not None:
            try:
                # בדיקה קטנה שהדפדפן חי ולא נסגר
                _ = self._driver.title
                return True
            except Exception:
                # משהו נשבר / היסגר - ננסה להתחבר מחדש
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

        # ניסיון להתחברות חדשה
        try:
            chrome_opts = Options()

            # החלק הקריטי:
            # זה אומר לסלניום "אל תפתח כרום חדש. תתחבר לכרום שכבר רץ פה"
            chrome_opts.debugger_address = f"{DEBUG_CHROME_HOST}:{DEBUG_CHROME_PORT}"

            # חשוב: כאן אנחנו מניחים שיש לך דרייבר כרום תואם במכונה הזאת
            # (chromedriver תואם לגרסת הכרום שאתה מריץ).
            self._driver = webdriver.Chrome(options=chrome_opts)
            return True

        except Exception as e:
            self.state.last_error = f"connect fail: {e}"
            # ננסה לנקות
            try:
                if self._driver:
                    self._driver.quit()
            except Exception:
                pass
            self._driver = None
            return False

    def _click_xpath(self, xpath: str) -> bool:
        """
        מנסה להתחבר לכרום ואז ללחוץ על האלמנט לפי ה-XPath.
        """
        try:
            if not self._connect_driver_if_needed():
                return False

            # חיפוש האלמנט
            el = self._driver.find_element(By.XPATH, xpath)

            # לחיצה
            el.click()
            return True

        except Exception as e:
            # נרשום שגיאה בשביל סטטוס
            self.state.last_error = f"click fail: {e}"
            traceback.print_exc()

            # אם היתה בעיה גדולה (נגיד חלון נסגר), ננתק את הדרייבר
            try:
                if self._driver:
                    # אל תעשה quit() מיידית בכל טעות קטנה, אבל
                    # אם זה באמת בעיית חיבור/דפדפן מת -> אפשר לשקול כן.
                    pass
            except Exception:
                pass

            return False
