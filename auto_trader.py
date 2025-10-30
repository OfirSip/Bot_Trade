# auto_trader.py
from __future__ import annotations
import os, time, traceback
from dataclasses import dataclass, field
from typing import Optional

# Selenium / Chrome DevTools connection
from selenium import webdriver # שים לב, אנחנו צריכים את webdriver הכללי
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# --- ספריות ל-Explicit Wait ---
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =====================================================================================
# קונפיג מהסביבה
# =====================================================================================

DEBUG_CHROME_HOST = os.getenv("DEBUG_CHROME_HOST", "127.0.0.1").strip()
DEBUG_CHROME_PORT = int(os.getenv("DEBUG_CHROME_PORT", "9222").strip())

DEFAULT_MIN_INTERVAL_SEC = int(os.getenv("AUTO_MIN_INTERVAL_SEC", "15").strip())
DEFAULT_THRESHOLD_ENTER = int(os.getenv("AUTO_THRESHOLD_ENTER", "70").strip())
DEFAULT_THRESHOLD_AGGR  = int(os.getenv("AUTO_THRESHOLD_AGGR", "80").strip())

# XPaths המעודכנים
XPATH_UP = "//a[contains(@class,'btn-call')]"
XPATH_DOWN = "//a[contains(@class,'btn-put')]"


# =====================================================================================
# מצב פנימי של המסחר האוטומטי
# =====================================================================================

@dataclass
class AutoState:
    enabled: bool = False
    threshold_enter: int = DEFAULT_THRESHOLD_ENTER
    threshold_aggr: int = DEFAULT_THRESHOLD_AGGR
    min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC
    last_action: Optional[str] = None
    last_action_ts: float = 0.0
    last_error: Optional[str] = None


class AutoTrader:
    def __init__(self):
        self.state = AutoState()
        self._driver: Optional[webdriver.Remote] = None # שונה ל-webdriver.Remote

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
        if not self.state.enabled:
            self._remember("SKIP", "Auto disabled")
            return False

        required = self.state.threshold_enter if strong_ok else self.state.threshold_aggr
        if conf < required:
            self._remember("SKIP", f"conf {conf} < required {required}")
            return False

        now = time.time()
        if now - self.state.last_action_ts < self.state.min_interval_sec:
            self._remember("SKIP", "cooldown/min_interval")
            return False

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
            self._remember("SKIP", f"failed click: {self.state.last_error}")

        return ok

    def manual_click_up(self) -> bool:
        ok = self._click_xpath(XPATH_UP)
        if ok:
            self._remember("MANUAL BUY↑", None)
        else:
            self._remember("MANUAL BUY↑", f"click fail: {self.state.last_error}")
        return ok

    def manual_click_down(self) -> bool:
        ok = self._click_xpath(XPATH_DOWN)
        if ok:
            self._remember("MANUAL SELL↓", None)
        else:
            self._remember("MANUAL SELL↓", f"click fail: {self.state.last_error}")
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
        """
        if self._driver is not None:
            try:
                _ = self._driver.title
                return True
            except Exception:
                try:
                    self._driver.quit()
                except Exception:
                    pass
                self._driver = None

        # ================================================================
        # --- כאן התיקון ---
        # ================================================================
        try:
            chrome_opts = Options()
            # אנו עדיין משתמשים ב-debugger_address כדי לומר ל-Selenium
            # לאיזה דפדפן/טאב להתחבר
            chrome_opts.debugger_address = f"{DEBUG_CHROME_HOST}:{DEBUG_CHROME_PORT}"

            # זו הכתובת של שרת ה-Selenium (שבמקרה שלנו הוא גם שרת הדיבאגר)
            executor_url = f"http://{DEBUG_CHROME_HOST}:{DEBUG_CHROME_PORT}"

            # החלפנו את webdriver.Chrome ב- webdriver.Remote
            # זה אומר לסלניום "אל תנסה להפעיל chromedriver מקומית,
            # פשוט תשלח פקודות HTTP לכתובת הזו"
            self._driver = webdriver.Remote(
                command_executor=executor_url,
                options=chrome_opts
            )
            
            # הגדרת Implicit Wait פעם אחת
            self._driver.implicitly_wait(3) 
            return True

        except Exception as e:
            self.state.last_error = f"connect fail: {e}"
            traceback.print_exc() # הדפסת השגיאה המלאה ללוג של Railway
            try:
                if self._driver:
                    self._driver.quit()
            except Exception:
                pass
            self._driver = None
            return False
        # ================================================================
        # --- סוף התיקון ---
        # ================================================================

    def _click_xpath(self, xpath: str) -> bool:
        """
        מנסה להתחבר לכרום ואז ללחוץ על האלמנט (עם המתנה חכמה).
        """
        try:
            if not self._connect_driver_if_needed():
                return False

            # המתנה חכמה (Explicit Wait)
            wait = WebDriverWait(self._driver, 5)
            el = wait.until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )

            # לחיצה
            el.click()
            return True

        except Exception as e:
            error_msg = str(e).split("\n")[0]
            self.state.last_error = f"click fail: {error_msg}"
            traceback.print_exc()
            return False
