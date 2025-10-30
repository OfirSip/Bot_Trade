POCKET_TO_FINNHUB = {
    "EUR/USD": "OANDA:EUR_USD",
    "GBP/USD": "OANDA:GBP_USD",
    "USD/JPY": "OANDA:USD_JPY",
    "USD/CHF": "OANDA:USD_CHF",
    "AUD/USD": "OANDA:AUD_USD",
    "NZD/USD": "OANDA:NZD_USD",
    "EUR/GBP": "OANDA:EUR_GBP",
    "EUR/JPY": "OANDA:EUR_JPY",
    "GOLD": "OANDA:XAU_USD",
    "SILVER": "OANDA:XAG_USD",
    "OIL": "OANDA:WTICO_USD",
    "SP500": "INDEX:SPX",
    "NASDAQ": "INDEX:IXIC",
    "DAX": "INDEX:DAX",
    "FTSE": "INDEX:FTSE",
    "BTC/USD": "BINANCE:BTCUSDT",
    "ETH/USD": "BINANCE:ETHUSDT",
    "LTC/USD": "BINANCE:LTCUSDT",
    "BNB/USD": "BINANCE:BNBUSDT",
}

def get_symbol_for_pocket(name: str) -> str:
    return POCKET_TO_FINNHUB.get(name.upper(), "")
