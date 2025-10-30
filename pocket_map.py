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

    # --- הוספות חדשות (עוד מט"ח) ---
    "AUD/JPY": "OANDA:AUD_JPY",
    "EUR/AUD": "OANDA:EUR_AUD",
    "GBP/AUD": "OANDA:GBP_AUD",
    "NZD/USD": "OANDA:NZD_USD",
    "EUR/CAD": "OANDA:EUR_CAD",
    "GBP/CHF": "OANDA:GBP_CHF",

    # Crypto (Finnhub sym mapping example)
    "BTC/USD": "BINANCE:BTCUSDT",
    "ETH/USD": "BINANCE:ETHUSDT",
    "LTC/USD": "BINANCE:LTCUSDT", # הוספה - לייטקוין
    
    # --- הוספות חדשות (עוד קריפטו) ---
    "XRP/USD": "BINANCE:XRPUSDT",
    "ADA/USD": "BINANCE:ADAUSDT",
    "DOGE/USD": "BINANCE:DOGEUSDT",


    # --- הוספות קיימות (כינויי OTC) ---
    "EUR/USD_otc": "OANDA:EUR_USD",
    "GBP/USD_otc": "OANDA:GBP_USD",
    "USD/JPY_otc": "OANDA:USD_JPY",
    "EURUSD OTC": "OANDA:EUR_USD",           # הוספה לבקשתך
    "BITCOIN OTC": "BINANCE:BTCUSDT",       # הוספה לבקשתך
    "ETH/USD OTC": "BINANCE:ETHUSDT",       # תיקון והוספה לבקשתך (עבור Eאיקרקוצ)
    "ETHEREUM OTC": "BINANCE:ETHUSDT",      # כינוי נוסף אפשרי

    # Commodities (סחורות)
    "Gold": "OANDA:XAUUSD",
    "XAU/USD": "OANDA:XAUUSD",
    "Silver": "OANDA:XAGUSD",
    "XAG/USD": "OANDA:XAGUSD",
    "Oil": "OANDA:WTICOUSD",
    "WTI Oil": "OANDA:WTICOUSD",
    # --- הוספות חדשות (סחורות) ---
    "Natural Gas": "OANDA:NATGASUSD",

    # Indices (מדדים)
    "S&P 500": "OANDA:SPX500USD",
    "US500": "OANDA:SPX500USD",
    "NASDAQ 100": "OANDA:NAS100USD",
    "US100": "OANDA:NAS100USD",
    # --- הוספות חדשות (מדדים) ---
    "Germany 40": "OANDA:DE30EUR", # DAX
    "DE30": "OANDA:DE30EUR",
    "UK 100": "OANDA:UK100GBP", # FTSE
    "UK100": "OANDA:UK100GBP",

    # Stocks (מניות נפוצות)
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "GOOGL": "GOOGL",
    "AMZN": "AMZN",
    "TSLA": "TSLA",
}

DEFAULT_SYMBOL = "OANDA:EUR_USD"
SUPPORTED_EXPIRIES = ["M1", "M3"]
