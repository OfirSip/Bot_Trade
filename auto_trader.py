from __future__ import annotations
import time, threading
from dataclasses import dataclass
from typing import Optional, Literal
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

Side = Literal["UP", "DOWN"]

# ===== הגדרות קשיחות (ללא ENV) =====
DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 9222

# XPaths לכפתורי עסקה ב-Pocket Option (לפי ה-HTML שסיפקת):
XPATH_UP   = "//div[contains(@class,'action-high-low') and contains(@class,'button-call-wrap')]//a[contains(@class,'btn-call')]"
XPATH_DOWN = "//div[contains(@class,'action-high-low') and contains(@class,'button-put-wrap')]//a[contains(@class,'btn-put')]"

@dataclass
class AutoState:
    enabled: bool = False
    last_trade_ts: float = 0.0
    last_side: Optional[Side] = None
    last_error: Optional[str] = None
    last_action: Optional[str] = None
    conf_threshold: int = 72       # סף ביטחון ברירת מחדל
    min_interval_sec: int = 15     # מינימום זמן בין טריידים
    anti_burst_sec: int = 5        # לא להיכנס פעמיים אותו כיוון מהר
    
    # --- הוספות חדשות ---
    last_check_ts: float = 0.0     # מתי הלולאה האוטומטית בדקה לאחרונה
    log_verbose: bool = False      # האם לדווח על עסקאות שנחסמו

class AutoTrader:
    """
    מתחבר ל-Chrome שפתוח במצב דיבאג:
      Windows לדוגמה:
        chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\ChromeDev"
      ואז פותחים ידנית את Pocket Option על הנכס/ה-Expiry הרצוי.
    """
    def __init__(self):
        self.state = AutoState()
        self._driver = None
        self._lock = threading.RLock()

    # ---------- Control ----------
    def enable(self):   self._set_enabled(True)
    def disable(self):  self._set_enabled(False)
    def _set_enabled(self, on: bool):
        with self._lock:
            self.state.enabled = on
            self.state.last_action = "enabled" if on else "disabled"
            if not on:
                self.state.last_check_ts = 0.0 # אפס בעת כיבוי

    def set_conf_threshold(self, v: int):
        with self._lock:
            self.state.conf_threshold = max(50, min(int(v), 95))

    def set_min_interval(self, v: int):
        with self._lock:
            self.state.min_interval_sec = max(3, int(v))

    # ---------- Driver ----------
    def _ensure_driver(self):
        """
        מוודא שיש דרייבר. במקום להתחבר לדפדפן קיים,
        הפונקציה הזו תפעיל אחד חדש במצב headless שמתאים לשרת.
        """
        if self._driver is not None:
            return
            
        opts = webdriver.ChromeOptions()
        # --- הגדרות קריטיות לשרת (Railway/GitHub) ---
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage") # חיוני בסביבות Docker
        opts.add_argument("--window-size=1920,1080")
        
        # הערה: הקוד הישן שמתחבר ל-9222 נמחק.
        # opts.debugger_address = f"{DEBUG_HOST}:{DEBUG_PORT}" # <-- DELETE THIS LINE
        try:
            # השתמש ב-webdriver_manager כדי להתקין אוטומטית את ה-chromedriver הנכון
            service = ChromeService(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=opts)
            
        except WebDriverException as e:
            self.state.last_error = f"WebDriver error: {e}"
            self.state.last_action = "error: webdriver init"
            # אם השגיאה היא 127, זה כנראה אומר ש-Chrome עצמו חסר
            if "Status code was: 127" in str(e):
                 self.state.last_error = "WebDriver error 127: 'google-chrome' not found or libs missing. Did you install it in the Dockerfile?"
            raise

    
    def _click(self, xpath: str):
        el = self._driver.find_element(By.XPATH, xpath)
        el.click()

    # ---------- Trade ----------
    def place_trade(self, side: Side) -> bool:
        """מנסה לבצע עסקה אוטומטית, מכבד את כל המגבלות"""
        with self._lock:
            if not self.state.enabled:
                self.state.last_action = "ignored: auto OFF"
                return False
            now = time.time()
            if now - self.state.last_trade_ts < self.state.min_interval_sec:
                self.state.last_action = "ignored: min_interval guard"
                return False
            if self.state.last_side == side and (now - self.state.last_trade_ts) < self.state.anti_burst_sec:
                self.state.last_action = "ignored: anti_burst same-side"
                return False

            try:
                self._ensure_driver()
                if side == "UP":
                    self._click(XPATH_UP)
                else:
                    self._click(XPATH_DOWN)
                self.state.last_trade_ts = now
                self.state.last_side = side
                self.state.last_error = None
                self.state.last_action = f"clicked {side}"
                return True
            except NoSuchElementException:
                self.state.last_error = f"xpath not found for {side}"
                self.state.last_action = "error: xpath not found"
                return False
            except WebDriverException as e:
                self.state.last_error = f"webdriver error: {e}"
                self.state.last_action = "error: webdriver"
                return False

    def force_manual_trade(self, side: Side) -> bool:
        """מבצע לחיצה ידנית בכוח, ללא קשר למצב 'enabled' או מגבלות (למעט נעילה)"""
        with self._lock:
            now = time.time()
            try:
                self._ensure_driver()
                if side == "UP":
                    self._click(XPATH_UP)
                else:
                    self._click(XPATH_DOWN)
                
                # אנחנו עדיין רושמים את זמן הלחיצה כדי שה-auto-trader יכבד אותה
                self.state.last_trade_ts = now
                self.state.last_side = side
                self.state.last_error = None
                self.state.last_action = f"MANUAL clicked {side}"
                return True
            except NoSuchElementException:
                self.state.last_error = f"xpath not found for {side} (manual)"
                self.state.last_action = "error: manual xpath not found"
                return False
            except WebDriverException as e:
                self.state.last_error = f"webdriver error: {e} (manual)"
                self.state.last_action = "error: manual webdriver"
                return False

    # ---------- Status ----------
    def status_lines(self) -> list[str]:
        with self._lock:
            last_check_str = "n/a"
            if self.state.last_check_ts > 0:
                last_check_str = time.strftime('%H:%M:%S', time.localtime(self.state.last_check_ts))

            return [
                f"AUTO: {'ON' if self.state.enabled else 'OFF'}",
                f"Conf threshold: {self.state.conf_threshold}",
                f"Min interval: {self.state.min_interval_sec}s",
                f"Anti-burst: {self.state.anti_burst_sec}s",
                f"Verbose Log: {'ON' if self.state.log_verbose else 'OFF'}", # הוספה
                f"Chrome debug: {DEBUG_HOST}:{DEBUG_PORT}",
                f"XPATH UP: {XPATH_UP}",
                f"XPATH DOWN: {XPATH_DOWN}",
                f"Last check: {last_check_str}", # הוספה
                f"Last action: {self.state.last_action or 'n/a'}",
                f"Last error: {self.state.last_error or 'none'}",
            ]
