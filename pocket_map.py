# pocket_map.py
PO_TO_FINNHUB = {
    # FX Majors
    "EUR/USD": "OANDA:EUR_USD",
    "GBP/USD": "OANDA:GBP_USD",
    "USD/JPY": "OANDA:USD_JPY",
    "USD/CHF": "OANDA:USD_CHF",
    "AUD/USD": "OANDA:AUD_USD",
    "USD/CAD": "OANDA:USD_CAD",
    "EUR/JPY": "OANDA:EUR_JPY",
    "GBP/JPY": "OANDA:GBP_JPY",
    "EUR/GBP": "OANDA:EUR_GBP",

    # Crypto (דוגמה – בדוק זמינות ב-Finnhub)
    "BTC/USD": "BINANCE:BTCUSDT",
    "ETH/USD": "BINANCE:ETHUSDT",

    # OTC (נמפה לבסיס הרגיל; PO מציע OTC בסופ״ש — תן fallback)
    "EUR/USD_otc": "OANDA:EUR_USD",
    "GBP/USD_otc": "OANDA:GBP_USD",
    "USD/JPY_otc": "OANDA:USD_JPY",
}
DEFAULT_SYMBOL = "OANDA:EUR_USD"

# זמן בררת מחדל ל-expiry בפוקט אופשן (שימוש כמטא בלבד)
SUPPORTED_EXPIRIES = ["M1", "M3"]
