# pocket_map.py
#
# מיפוי בין שם הנכס שאתה בוחר בטלגרם לבין הסימבול בסוקט של Finnhub
# אם תרצה להוסיף עוד, תוסיף כאן מיפוי "מה שאתה רואה בטלגרם": "SYMBOL"
#
# הערה חשובה:
#   Finnhub מקבל למשל:
#   - מט"ח דרך OANDA:  "OANDA:EUR_USD"
#   - קריפטו דרך BINANCE: "BINANCE:BTCUSDT"
#   - מדדים / סחורות גם דרך OANDA, לדוגמה "OANDA:SPX500USD"
#   - מניות אמריקאיות רבות פשוט לפי ה-ticker (AAPL, MSFT...)
#
# DEFAULT_SYMBOL הוא מה נטען אם מסיבה כלשהי אין מיפוי.
# SUPPORTED_EXPIRIES נשאר לרפרנס חיצוני, כרגע לא בשימוש ישיר בקוד.
#

PO_TO_FINNHUB = {
    # =========================
    # FX Majors
    # =========================
    "EUR/USD": "OANDA:EUR_USD",
    "GBP/USD": "OANDA:GBP_USD",
    "USD/JPY": "OANDA:USD_JPY",
    "USD/CHF": "OANDA:USD_CHF",
    "AUD/USD": "OANDA:AUD_USD",
    "USD/CAD": "OANDA:USD_CAD",
    "EUR/JPY": "OANDA:EUR_JPY",
    "GBP/JPY": "OANDA:GBP_JPY",
    "EUR/GBP": "OANDA:EUR_GBP",

    # זוגות נוספים נפוצים (הרחבה):
    "NZD/USD": "OANDA:NZD_USD",
    "EUR/CAD": "OANDA:EUR_CAD",
    "EUR/AUD": "OANDA:EUR_AUD",
    "AUD/JPY": "OANDA:AUD_JPY",
    "CAD/JPY": "OANDA:CAD_JPY",
    "CHF/JPY": "OANDA:CHF_JPY",
    "GBP/CAD": "OANDA:GBP_CAD",
    "GBP/CHF": "OANDA:GBP_CHF",
    "EUR/CHF": "OANDA:EUR_CHF",

    # =========================
    # Crypto
    # =========================
    "BTC/USD": "BINANCE:BTCUSDT",
    "ETH/USD": "BINANCE:ETHUSDT",
    "LTC/USD": "BINANCE:LTCUSDT",
    "BNB/USD": "BINANCE:BNBUSDT",
    "SOL/USD": "BINANCE:SOLUSDT",
    "DOGE/USD": "BINANCE:DOGEUSDT",
    "XRP/USD": "BINANCE:XRPUSDT",
    "ADA/USD": "BINANCE:ADAUSDT",
    "MATIC/USD": "BINANCE:MATICUSDT",

    # כינויים חלופיים (OTC / ניסוחים ידניים שלך)
    "EUR/USD_otc": "OANDA:EUR_USD",
    "GBP/USD_otc": "OANDA:GBP_USD",
    "USD/JPY_otc": "OANDA:USD_JPY",

    "EURUSD OTC": "OANDA:EUR_USD",
    "BITCOIN OTC": "BINANCE:BTCUSDT",
    "ETH/USD OTC": "BINANCE:ETHUSDT",
    "ETHEREUM OTC": "BINANCE:ETHUSDT",
    "BTCUSDT": "BINANCE:BTCUSDT",
    "ETHUSDT": "BINANCE:ETHUSDT",

    # =========================
    # Commodities (סחורות)
    # =========================
    "Gold": "OANDA:XAUUSD",
    "XAU/USD": "OANDA:XAUUSD",
    "Silver": "OANDA:XAGUSD",
    "XAG/USD": "OANDA:XAGUSD",
    "Oil": "OANDA:WTICOUSD",
    "WTI Oil": "OANDA:WTICOUSD",
    "Brent Oil": "OANDA:BCOUSD",    # ברנט
    "Natural Gas": "OANDA:NATGASUSD",

    # =========================
    # Indices (מדדים)
    # =========================
    "S&P 500": "OANDA:SPX500USD",
    "US500": "OANDA:SPX500USD",
    "NASDAQ 100": "OANDA:NAS100USD",
    "US100": "OANDA:NAS100USD",
    "DAX 40": "OANDA:DE30EUR",      # DAX (חלק מהברוקרים קוראים לזה DE30)
    "Dow Jones": "OANDA:US30USD",
    "FTSE 100": "OANDA:UK100GBP",
    "Nikkei 225": "OANDA:JP225USD",

    # =========================
    # Stocks / מניות פופולריות
    # =========================
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "GOOGL": "GOOGL",
    "AMZN": "AMZN",
    "TSLA": "TSLA",
    "NVDA": "NVDA",
    "META": "META",
    "NFLX": "NFLX",
    "AMD": "AMD",
    "INTC": "INTC",
    "BABA": "BABA",
    "NIO": "NIO",
    "PLTR": "PLTR",
    "COIN": "COIN",  # Coinbase (חשוב אם אתה סוחר קריפטו דרך חשיפת מניה)
}

DEFAULT_SYMBOL = "OANDA:EUR_USD"
SUPPORTED_EXPIRIES = ["M1", "M3", "M5", "M15"]
