# auto_trader.py
from __future__ import annotations
import time, threading
from dataclasses import dataclass
from typing import Optional, Literal

Side = Literal["UP", "DOWN"]

# ננסה לייבא Selenium. אם אין, נשאר במצב פסיבי.
SELENIUM_OK = True
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import NoSuchElementException, WebDriverException
except Exception:
    SELENIUM_OK = False
    webdriver = By = NoSuchElementException = WebDriverException = object  # type: ignore

DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 9222

# XPaths של כפתורי BUY/SELL ב-PO
XPATH_UP   = "//div[contains(@class,'action-high-low') and contains(@class,'button-call-wrap')]//a[contains(@class,'btn-call')]"
XPATH_DOWN = "//div[contains(@class,'action-high-low') and contains(@class,'button-put-wrap')]//a[contains(@class,'btn-put')]"

@dataclass
class AutoState:
    enabled: bool = False
    last_trade_ts: float = 0.0
    last_side: Optional[Side] = None
    last_error: Optional[str] = None
    last_action: Optional[str] = None

    # thresholds:
    threshold_enter: int = 72        # כניסה רגילה
    threshold_aggr: int  = 65        # כניסה אגרסיבית (דורש תנאים מחמירים)
    min_interval_sec: int = 15       # מניעת ספאם רצוף
    anti_flip_sec: int   = 5         # בלימת היפוך מהיר

    # telemetry:
    last_attempt_side: Optional[Side] = None
    last_attempt_conf: Optional[int] = None
    last_decision_reason: Optional[str] = None

class AutoTrader:
    """
    מחובר ל-Chrome שעובד בדיבאג:
      chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\ChromeDev"
    אם Selenium לא זמין → לא לוחץ בפועל אבל עדיין "מסביר מה היה קורה".
    """
    def __init__(self):
        self.state = AutoState()
        self._driver = None
        self._lock = threading.RLock()
        if not SELENIUM_OK:
            self.state.last_error = "Selenium not installed; auto-trading disabled"

    def enable(self):
        with self._lock:
            if not SELENIUM_OK:
                self.state.enabled = False
                self.state.last_action = "failed enable (no selenium)"
                self.state.last_error = "Install selenium to enable"
            else:
                self.state.enabled = True
                self.state.last_action = "enabled"

    def disable(self):
        with self._lock:
            self.state.enabled = False
            self.state.last_action = "disabled"

    def set_threshold_enter(self, v: int):
        with self._lock:
            self.state.threshold_enter = max(55, min(int(v), 95))

    def set_threshold_aggr(self, v: int):
        with self._lock:
            self.state.threshold_aggr = max(50, min(int(v), 90))

    def set_min_interval(self, v: int):
        with self._lock:
            self.state.min_interval_sec = max(3, int(v))

    def _ensure_driver(self):
        if not SELENIUM_OK:
            raise RuntimeError("Selenium unavailable")
        if self._driver is not None:
            return
        opts = webdriver.ChromeOptions()  # type: ignore[attr-defined]
        opts.debugger_address = f"{DEBUG_HOST}:{DEBUG_PORT}"  # type: ignore[attr-defined]
        self._driver = webdriver.Chrome(options=opts)  # type: ignore[call-arg]

    def _click_xpath(self, xpath: str):
        if not SELENIUM_OK:
            raise RuntimeError("Selenium unavailable")
        el = self._driver.find_element(By.XPATH, xpath)  # type: ignore[attr-defined]
        el.click()

    def can_trade_now(self, side: Side, conf: int, strong_ok: bool, now: float) -> (bool,str):
        """
        strong_ok = האם זה סיגנל איכותי חזק (הסכמה של טווחים וכו')
        """
        if not self.state.enabled:
            return False, "auto OFF"

        # anti-spam
        dt = now - self.state.last_trade_ts
        if dt < self.state.min_interval_sec:
            return False, f"cooldown {self.state.min_interval_sec-dt:.1f}s left"

        # anti-flip
        if self.state.last_side and self.state.last_side != side and dt < self.state.anti_flip_sec:
            return False, "anti-flip guard"

        # decide threshold logic
        if conf >= self.state.threshold_enter:
            return True, ">=enter threshold"
        if conf >= self.state.threshold_aggr and strong_ok:
            return True, ">=aggr+strong"
        return False, "conf too low"

    def place_if_allowed(self, side: Side, conf: int, strong_ok: bool):
        with self._lock:
            now = time.time()
            ok, reason = self.can_trade_now(side, conf, strong_ok, now)
            self.state.last_attempt_side = side
            self.state.last_attempt_conf = conf
            self.state.last_decision_reason = reason

            if not ok:
                self.state.last_action = f"skipped ({reason})"
                return False

            # אפילו אם ok, יכול להיות שאין selenium בפועל
            if not SELENIUM_OK:
                self.state.last_error = "no selenium (dry)"
                self.state.last_action = f"DRY would {side}"
                self.state.last_trade_ts = now
                self.state.last_side = side
                return True

            # אמור לבצע קליק אמיתי
            try:
                self._ensure_driver()
                if side == "UP":
                    self._click_xpath(XPATH_UP)
                else:
                    self._click_xpath(XPATH_DOWN)
                self.state.last_trade_ts = now
                self.state.last_side = side
                self.state.last_error = None
                self.state.last_action = f"clicked {side}"
                return True
            except NoSuchElementException:
                self.state.last_error = "xpath not found"
                self.state.last_action = "error: xpath"
                return False
            except WebDriverException as e:  # type: ignore[name-defined]
                self.state.last_error = f"webdriver error: {e}"
                self.state.last_action = "error: webdriver"
                return False
            except Exception as e:
                self.state.last_error = f"{type(e).__name__}: {e}"
                self.state.last_action = "error"
                return False

    def next_allowed_seconds(self) -> float:
        with self._lock:
            dt = time.time() - self.state.last_trade_ts
            left = self.state.min_interval_sec - dt
            return left if left>0 else 0.0

    def status_lines(self) -> list[str]:
        with self._lock:
            return [
                f"AUTO: {'ON' if self.state.enabled else 'OFF'}",
                f"Threshold enter: {self.state.threshold_enter}",
                f"Threshold aggr: {self.state.threshold_aggr}",
                f"Min interval: {self.state.min_interval_sec}s",
                f"Anti-flip: {self.state.anti_flip_sec}s",
                f"Next allowed in: {self.next_allowed_seconds():.1f}s",
                f"Last action: {self.state.last_action or 'n/a'}",
                f"Last try: side={self.state.last_attempt_side} conf={self.state.last_attempt_conf} reason={self.state.last_decision_reason}",
                f"Selenium: {'OK' if SELENIUM_OK else 'NOT INSTALLED'}",
                f"Chrome debug: {DEBUG_HOST}:{DEBUG_PORT}",
                f"XPATH_UP: {XPATH_UP}",
                f"XPATH_DOWN: {XPATH_DOWN}",
                f"Last error: {self.state.last_error or 'none'}",
            ]
