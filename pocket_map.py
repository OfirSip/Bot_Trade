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

    # Crypto (Finnhub sym mapping example)
    "BTC/USD": "BINANCE:BTCUSDT",
    "ETH/USD": "BINANCE:ETHUSDT",
    "LTC/USD": "BINANCE:LTCUSDT", # הוספה - לייטקוין

    # --- הוספות חדשות ---

    # OTC aliases → map to base instruments
    # (Original)
    "EUR/USD_otc": "OANDA:EUR_USD",
    "GBP/USD_otc": "OANDA:GBP_USD",
    "USD/JPY_otc": "OANDA:USD_JPY",
    
    # (User Requests - הוספות משתמש)
    "EURUSD OTC": "OANDA:EUR_USD",           # הוספה לבקשתך
    "BITCOIN OTC": "BINANCE:BTCUSDT",       # הוספה לבקשתך
    "ETH/USD OTC": "BINANCE:ETHUSDT",       # תיקון והוספה לבקשתך (עבור Eאיקרקוצ)
    "ETHEREUM OTC": "BINANCE:ETHUSDT",      # כינוי נוסף אפשרי

    # Commodities (הוספות - סחורות)
    "Gold": "OANDA:XAUUSD",
    "XAU/USD": "OANDA:XAUUSD",
    "Silver": "OANDA:XAGUSD",
    "XAG/USD": "OANDA:XAGUSD",
    "Oil": "OANDA:WTICOUSD",
    "WTI Oil": "OANDA:WTICOUSD",

    # Indices (הוספות - מדדים)
    "S&P 500": "OANDA:SPX500USD",
    "US500": "OANDA:SPX500USD",
    "NASDAQ 100": "OANDA:NAS100USD",
    "US100": "OANDA:NAS100USD",

    # Stocks (הוספות - מניות נפוצות)
    # For US stocks, Finnhub often just uses the ticker
    # עבור מניות אמריקאיות, Finnhub לרוב משתמש בטיקר בלבד
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "GOOGL": "GOOGL",
    "AMZN": "AMZN",
    "TSLA": "TSLA",
}

DEFAULT_SYMBOL = "OANDA:EUR_USD"
SUPPORTED_EXPIRIES = ["M1", "M3"]
