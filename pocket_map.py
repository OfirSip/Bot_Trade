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

    # OTC aliases → map to base instruments
    "EUR/USD_otc": "OANDA:EUR_USD",
    "GBP/USD_otc": "OANDA:GBP_USD",
    "USD/JPY_otc": "OANDA:USD_JPY",
}

DEFAULT_SYMBOL = "OANDA:EUR_USD"
SUPPORTED_EXPIRIES = ["M1", "M3"]
