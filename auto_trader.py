# auto_trader.py
from __future__ import annotations
import os, time, threading
from dataclasses import dataclass, field
from typing import Optional, Literal

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

Side = Literal["UP", "DOWN"]

@dataclass
class AutoConfig:
    host: str = os.getenv("REMOTE_DEBUG_HOST", "127.0.0.1")
    port: int = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))
    up_xpath: Optional[str] = os.getenv("PO_UP_XPATH")
    down_xpath: Optional[str] = os.getenv("PO_DOWN_XPATH")
    amount_xpath: Optional[str] = os.getenv("PO_AMOUNT_XPATH")  # אופציונלי
    amount_value: Optional[str] = os.getenv("PO_AMOUNT_VALUE")  # למשל "1", "3", "10"
    min_interval_sec: int = int(os.getenv("AUTO_MIN_INTERVAL_SEC", "15"))  # מרווח מינימלי בין טריידים
    conf_threshold: int = int(os.getenv("AUTO_CONF_THRESHOLD", "72"))       # סף ביטחון לברירת מחדל
    dry_run: bool = os.getenv("AUTO_DRY_RUN", "false").lower() == "true"    # אם true לא ילחץ בפועל
    # הגנה כפולה: לא לבצע פעמיים באותו כיוון בפחות מ-X שניות
    anti_burst_sec: int = int(os.getenv("AUTO_ANTI_BURST_SEC", "5"))

@dataclass
class AutoState:
    enabled: bool = False
    last_trade_ts: float = 0.0
    last_side: Optional[Side] = None
    last_error: Optional[str] = None
    last_action: Optional[str] = None
    conf_threshold: int = 72
    min_interval_sec: int = 15

class AutoTrader:
    def __init__(self, cfg: AutoConfig):
        self.cfg = cfg
        self.state = AutoState(
            enabled=False,
            conf_threshold=cfg.conf_threshold,
            min_interval_sec=cfg.min_interval_sec
        )
        self._driver = None
        self._lock = threading.RLock()

    def _ensure_driver(self):
        if self._driver is not None:
            return
        opts = webdriver.ChromeOptions()
        opts.debugger_address = f"{self.cfg.host}:{self.cfg.port}"
        try:
            self._driver = webdriver.Chrome(options=opts)
        except WebDriverException as e:
            self.state.last_error = f"WebDriver error: {e}"
            raise

    def _click_xpath(self, xpath: str) -> None:
        el = self._driver.find_element(By.XPATH, xpath)
        el.click()

    def _set_amount_if_needed(self):
        if not self.cfg.amount_xpath or self.cfg.amount_value is None:
            return
        try:
            el = self._driver.find_element(By.XPATH, self.cfg.amount_xpath)
            # ניקוי והזנה עדינה
            el.click()
            el.clear()
            el.send_keys(str(self.cfg.amount_value))
        except NoSuchElementException:
            self.state.last_error = "Amount xpath not found"

    def place_trade(self, side: Side) -> bool:
        with self._lock:
            if not self.state.enabled:
                self.state.last_action = "ignored: auto disabled"
                return False
            now = time.time()
            if now - self.state.last_trade_ts < self.state.min_interval_sec:
                self.state.last_action = "ignored: min_interval guard"
                return False
            if self.state.last_side == side and (now - self.state.last_trade_ts) < self.cfg.anti_burst_sec:
                self.state.last_action = "ignored: anti_burst same-side"
                return False
            if not self.cfg.up_xpath or not self.cfg.down_xpath:
                self.state.last_error = "Missing PO_UP_XPATH/PO_DOWN_XPATH"
                self.state.last_action = "error: missing xpaths"
                return False

            if self.cfg.dry_run:
                self.state.last_trade_ts = now
                self.state.last_side = side
                self.state.last_action = f"DRY_RUN click {side}"
                return True

            try:
                self._ensure_driver()
                # סכום (אם הוגדר)
                self._set_amount_if_needed()
                # לחיצה
                if side == "UP":
                    self._click_xpath(self.cfg.up_xpath)
                else:
                    self._click_xpath(self.cfg.down_xpath)
                self.state.last_trade_ts = now
                self.state.last_side = side
                self.state.last_action = f"clicked {side}"
                self.state.last_error = None
                return True
            except NoSuchElementException:
                self.state.last_error = f"xpath not found for {side.lower()}"
                self.state.last_action = "error: xpath not found"
                return False
            except WebDriverException as e:
                self.state.last_error = f"webdriver error: {e}"
                self.state.last_action = "error: webdriver"
                return False

    # === בקרות מצב ===
    def enable(self):
        with self._lock:
            self.state.enabled = True
            self.state.last_action = "enabled"

    def disable(self):
        with self._lock:
            self.state.enabled = False
            self.state.last_action = "disabled"

    def set_conf_threshold(self, v: int):
        with self._lock:
            self.state.conf_threshold = int(v)

    def set_min_interval(self, v: int):
        with self._lock:
            self.state.min_interval_sec = int(v)

    def status_lines(self) -> list[str]:
        with self._lock:
            return [
                f"AUTO: {'ON' if self.state.enabled else 'OFF'}",
                f"Conf threshold: {self.state.conf_threshold}",
                f"Min interval: {self.state.min_interval_sec}s",
                f"Anti-burst: {self.cfg.anti_burst_sec}s",
                f"Chrome: {self.cfg.host}:{self.cfg.port}",
                f"UP xpath set: {bool(self.cfg.up_xpath)}",
                f"DOWN xpath set: {bool(self.cfg.down_xpath)}",
                f"Amount xpath set: {bool(self.cfg.amount_xpath)}; value={self.cfg.amount_value}",
                f"Last action: {self.state.last_action or 'n/a'}",
                f"Last error: {self.state.last_error or 'none'}",
            ]
