from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "oracle.db"

ASSETS = [
    {
        "symbol": "BTC",
        "name": "Bitcoin",
        "coingecko_id": "bitcoin",
        "keywords": ["bitcoin", "btc", "биткоин"],
    },
    {
        "symbol": "ETH",
        "name": "Ethereum",
        "coingecko_id": "ethereum",
        "keywords": ["ethereum", "ether", "eth", "эфириум"],
    },
    {
        "symbol": "SOL",
        "name": "Solana",
        "coingecko_id": "solana",
        "keywords": ["solana", "sol"],
    },
    {
        "symbol": "BNB",
        "name": "BNB",
        "coingecko_id": "binancecoin",
        "keywords": ["bnb", "binance coin", "binance"],
    },
    {
        "symbol": "XRP",
        "name": "XRP",
        "coingecko_id": "ripple",
        "keywords": ["xrp", "ripple"],
    },
    {
        "symbol": "DOGE",
        "name": "Dogecoin",
        "coingecko_id": "dogecoin",
        "keywords": ["dogecoin", "doge"],
    },
    {
        "symbol": "ADA",
        "name": "Cardano",
        "coingecko_id": "cardano",
        "keywords": ["cardano", "ada"],
    },
    {
        "symbol": "AVAX",
        "name": "Avalanche",
        "coingecko_id": "avalanche-2",
        "keywords": ["avalanche", "avax"],
    },
    {
        "symbol": "LINK",
        "name": "Chainlink",
        "coingecko_id": "chainlink",
        "keywords": ["chainlink", "link"],
    },
    {
        "symbol": "TON",
        "name": "Toncoin",
        "coingecko_id": "the-open-network",
        "keywords": ["toncoin", "ton", "telegram"],
    },
]

SOURCES = [
    {
        "code": "coingecko",
        "name": "CoinGecko Markets",
        "kind": "market",
        "url": "https://api.coingecko.com/api/v3/coins/markets",
    },
    {
        "code": "fear_greed",
        "name": "Alternative.me Fear & Greed",
        "kind": "index",
        "url": "https://api.alternative.me/fng/",
    },
    {
        "code": "cryptocompare_news",
        "name": "CryptoCompare News",
        "kind": "news",
        "url": "https://min-api.cryptocompare.com/data/v2/news/",
    },
    {
        "code": "coindesk_rss",
        "name": "CoinDesk RSS",
        "kind": "news",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    },
    {
        "code": "cointelegraph_rss",
        "name": "Cointelegraph RSS",
        "kind": "news",
        "url": "https://cointelegraph.com/rss",
    },
]

RSS_FEEDS = [
    ("coindesk_rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph_rss", "https://cointelegraph.com/rss"),
]

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
FEAR_GREED_URL = "https://api.alternative.me/fng/"
CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

HTTP_TIMEOUT = 25.0
CHART_DAYS = 8
BACKTEST_DAYS = 6
FORECAST_HORIZON_HOURS = 24
USER_AGENT = "FutureOracle/1.0 (educational prototype; no trading)"
