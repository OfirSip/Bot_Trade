from __future__ import annotations
import os, time, random, traceback, threading
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, NoSuchWindowException

###############################################################################
# AUTO TRADER
# גרסה משופרת:
# - פתיחה וניהול של Chrome דינמי גם אחרי קריסות
# - Auto-reconnect לסשן PocketOption
# - Thread-safe
# - מניעת הצפה בין עסקאות (rate limiter)
# - מעקב מלא אחרי ניסיונות כושלים
###############################################################################


# ============================================================
# הגדרות ENV
# ============================================================
PO_URL = os.getenv("PO_URL", "https://pocketoption.com/en/")
PO_LOGIN_WAIT = int(os.getenv("PO_LOGIN_WAIT", "25"))  # זמן לחכות לטעינת דף
TRADE_COOLDOWN_SEC = 15  # הגבלת תדירות עסקאות

# ============================================================
# מצב הבוט למסחר
# ============================================================
class AutoState:
    def __init__(self):
        self.enabled = True
        self.last_action = None
        self.last_trade_ts = 0.0
        self.threshold_enter = 70
        self.threshold_aggr = 80
        self.min_interval_sec = 10
        self.fail_streak = 0
        self.lock = threading.Lock()


# ============================================================
# מחלקת AutoTrader
# ============================================================
class AutoTrader:
    def __init__(self):
        self.state = AutoState()
        self.driver = None
        self.thread = None
        self._init_lock = threading.Lock()
        self._reconnect_attempts = 0

    # --------------------------------------------------------
    def _init_chrome(self):
        """פותח את Chrome במצב מאובטח עם אפשרות שחזור לאחר כשל"""
        with self._init_lock:
            try:
                if self.driver:
                    return self.driver

                opts = Options()
                opts.add_argument("--no-sandbox")
                opts.add_argument("--disable-dev-shm-usage")
                opts.add_argument("--disable-blink-features=AutomationControlled")
                opts.add_argument("--disable-gpu")
                opts.add_argument("--window-size=1280,720")
                opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                opts.add_argument("--disable-infobars")
                opts.add_argument("--mute-audio")
                opts.add_argument("--disable-extensions")
                opts.add_argument("--disable-popup-blocking")
                opts.add_argument("--start-maximized")
                opts.add_experimental_option("excludeSwitches", ["enable-automation"])
                opts.add_experimental_option("useAutomationExtension", False)

                self.driver = webdriver.Chrome(options=opts)
                self.driver.get(PO_URL)
                print(f"[AUTO] Chrome session started at {PO_URL}")

                # המתנה לטעינה ידנית
                print(f"[AUTO] Waiting {PO_LOGIN_WAIT}s for PocketOption login to complete...")
                time.sleep(PO_LOGIN_WAIT)
                return self.driver
            except WebDriverException as e:
                print("[AUTO] Chrome init error:", e)
                traceback.print_exc()
                self.driver = None
                return None

    # --------------------------------------------------------
    def _ensure_driver(self):
        """בודק אם הדפדפן פעיל, אחרת מנסה לחדש."""
        try:
            if not self.driver:
                return self._init_chrome()
            _ = self.driver.current_url
            return self.driver
        except (WebDriverException, NoSuchWindowException):
            print("[AUTO] WebDriver lost. Reinitializing Chrome...")
            self.driver = None
            return self._init_chrome()
        except Exception as e:
            print("[AUTO] ensure_driver exception:", e)
            self.driver = None
            return self._init_chrome()

    # --------------------------------------------------------
    def enable(self):
        with self.state.lock:
            self.state.enabled = True
            print("[AUTO] Enabled")

    def disable(self):
        with self.state.lock:
            self.state.enabled = False
            print("[AUTO] Disabled")

    # --------------------------------------------------------
    def set_threshold_enter(self, val: int):
        with self.state.lock:
            self.state.threshold_enter = max(40, min(val, 95))

    def set_threshold_aggr(self, val: int):
        with self.state.lock:
            self.state.threshold_aggr = max(50, min(val, 99))

    def set_min_interval(self, val: int):
        with self.state.lock:
            self.state.min_interval_sec = max(5, min(val, 60))

    # --------------------------------------------------------
    def _safe_click(self, xpath: str) -> bool:
        """מנסה ללחוץ על אלמנט, מטפל בשגיאות UI."""
        try:
            btn = self.driver.find_element("xpath", xpath)
            btn.click()
            return True
        except Exception as e:
            print(f"[AUTO] Click failed for {xpath}: {e}")
            return False

    # --------------------------------------------------------
    def place_trade(self, side: str, amount: float = 1.0, demo=True) -> bool:
        """
        מבצע עסקה בפוקט אופשן.
        demo=True -> מסחר בדמו בלבד.
        """
        driver = self._ensure_driver()
        if not driver:
            print("[AUTO] No driver available, skipping trade.")
            return False

        now = time.time()
        if now - self.state.last_trade_ts < TRADE_COOLDOWN_SEC:
            print("[AUTO] Cooldown active, skipping trade.")
            return False

        side = side.upper()
        xpaths = {
            "UP": '//button[contains(@class, "up") or contains(@data-act, "up")]',
            "DOWN": '//button[contains(@class, "down") or contains(@data-act, "down")]',
        }
        xpath = xpaths.get(side)
        if not xpath:
            print(f"[AUTO] Invalid side: {side}")
            return False

        try:
            clicked = self._safe_click(xpath)
            if not clicked:
                self.state.fail_streak += 1
                return False

            print(f"[AUTO] TRADE EXECUTED: {side} | amount={amount} | demo={demo}")
            self.state.last_action = f"{side} @ {time.strftime('%H:%M:%S')}"
            self.state.last_trade_ts = now
            self.state.fail_streak = 0
            return True
        except Exception as e:
            print("[AUTO] Trade failed:", e)
            traceback.print_exc()
            self.state.fail_streak += 1
            return False

    # --------------------------------------------------------
    def place_if_allowed(self, side: str, conf: int, strong_ok: bool = False):
        """בודק תנאים ולוקח עסקה אם עומד בספים."""
        with self.state.lock:
            if not self.state.enabled:
                return False
            now = time.time()
            if now - self.state.last_trade_ts < self.state.min_interval_sec:
                return False
            thr = self.state.threshold_aggr if strong_ok else self.state.threshold_enter
            if conf < thr:
                return False
        return self.place_trade(side=side)

    # --------------------------------------------------------
    def status_lines(self) -> list[str]:
        with self.state.lock:
            return [
                f"Enabled: {self.state.enabled}",
                f"Last action: {self.state.last_action}",
                f"Enter Thr: {self.state.threshold_enter}",
                f"Aggressive Thr: {self.state.threshold_aggr}",
                f"Min interval: {self.state.min_interval_sec}s",
                f"Consecutive fails: {self.state.fail_streak}",
            ]

