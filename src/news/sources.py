"""
News source definitions — RSS feeds, API endpoints, and sector tags.
Add or remove sources freely; the fetcher uses this registry.
"""

from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Sector taxonomy
# ---------------------------------------------------------------------------
SECTORS = [
    "technology",
    "artificial_intelligence",
    "financial_services",
    "energy",
    "healthcare",
    "consumer",
    "real_estate",
    "crypto",
    "defense",
    "commodities",
    "macro",
]

# ---------------------------------------------------------------------------
# RSS feed registry — completely free, no API key required
# ---------------------------------------------------------------------------
@dataclass
class RSSSource:
    name: str
    url: str
    sectors: List[str] = field(default_factory=list)   # empty = general
    weight: float = 1.0                                # relevance weight

RSS_SOURCES: List[RSSSource] = [
    # ── General Finance & Macro ──────────────────────────────────────────
    # Note: Reuters discontinued free RSS in 2023; Yahoo/MarketWatch/CNBC still work.
    RSSSource("Yahoo Finance",         "https://finance.yahoo.com/news/rss/",                              weight=1.3),
    RSSSource("MarketWatch Top",       "https://feeds.marketwatch.com/marketwatch/topstories/",            ["macro", "financial_services"]),
    RSSSource("MarketWatch Markets",   "https://feeds.marketwatch.com/marketwatch/marketpulse/",           ["macro"]),
    RSSSource("CNBC Finance",          "https://www.cnbc.com/id/10000664/device/rss/rss.html",             ["macro", "financial_services"]),
    RSSSource("CNBC Economy",          "https://www.cnbc.com/id/20910258/device/rss/rss.html",             ["macro"]),
    RSSSource("Seeking Alpha",         "https://seekingalpha.com/market_currents.xml",                     weight=1.2),
    RSSSource("Investopedia News",     "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline"),
    RSSSource("The Motley Fool",       "https://www.fool.com/feeds/index.aspx",                            ["macro", "financial_services"]),
    RSSSource("Barron's",              "https://www.barrons.com/xml/rss/3_7510.xml",                       ["macro", "financial_services"], weight=1.2),
    RSSSource("WSJ Markets",           "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",      ["macro", "financial_services"], weight=1.2),

    # ── Technology & AI ──────────────────────────────────────────────────
    RSSSource("CNBC Technology",       "https://www.cnbc.com/id/19854910/device/rss/rss.html",             ["technology"]),
    RSSSource("TechCrunch",            "https://techcrunch.com/feed/",                                     ["technology", "artificial_intelligence"]),
    RSSSource("VentureBeat AI",        "https://venturebeat.com/category/ai/feed/",                        ["artificial_intelligence"], weight=1.5),
    RSSSource("MIT Tech Review",       "https://www.technologyreview.com/feed/",                           ["technology", "artificial_intelligence"], weight=1.3),
    RSSSource("The Verge",             "https://www.theverge.com/rss/index.xml",                           ["technology"]),
    RSSSource("Wired Business",        "https://www.wired.com/feed/category/business/latest/rss",          ["technology"]),
    RSSSource("Hacker News (top)",     "https://hnrss.org/frontpage?points=100",                           ["technology"]),
    RSSSource("Ars Technica Business", "https://feeds.arstechnica.com/arstechnica/business",               ["technology"], weight=1.1),
    RSSSource("IEEE Spectrum",         "https://spectrum.ieee.org/feeds/feed.rss",                         ["technology", "artificial_intelligence"]),

    # ── Financial Services & Banking ─────────────────────────────────────
    RSSSource("Financial Times",       "https://www.ft.com/rss/home",                                      ["financial_services", "macro"], weight=1.3),
    RSSSource("American Banker",       "https://www.americanbanker.com/feed",                              ["financial_services"]),

    # ── Crypto & DeFi ────────────────────────────────────────────────────
    RSSSource("CoinDesk",              "https://www.coindesk.com/arc/outboundfeeds/rss/",                  ["crypto"], weight=1.2),
    RSSSource("Cointelegraph",         "https://cointelegraph.com/rss",                                    ["crypto"]),
    RSSSource("Decrypt",               "https://decrypt.co/feed",                                          ["crypto"]),
    RSSSource("The Block",             "https://www.theblock.co/rss.xml",                                  ["crypto"], weight=1.2),
    RSSSource("Bitcoin Magazine",      "https://bitcoinmagazine.com/feed",                                 ["crypto"]),

    # ── Energy & Commodities ─────────────────────────────────────────────
    RSSSource("OilPrice.com",          "https://oilprice.com/rss/main",                                    ["energy", "commodities"]),
    RSSSource("S&P Global Energy",     "https://www.spglobal.com/commodityinsights/en/rss-feed/oil",       ["energy", "commodities"]),
    RSSSource("Renewable Energy World","https://www.renewableenergyworld.com/feed/",                        ["energy"]),

    # ── Healthcare & Biotech ─────────────────────────────────────────────
    RSSSource("STAT News",             "https://www.statnews.com/feed/",                                   ["healthcare"], weight=1.3),
    RSSSource("FierceBiotech",         "https://www.fiercebiotech.com/rss/xml",                            ["healthcare"]),
    RSSSource("BioPharma Dive",        "https://www.biopharmadive.com/feeds/news/",                        ["healthcare"], weight=1.2),
    RSSSource("MedCity News",          "https://medcitynews.com/feed/",                                    ["healthcare"]),

    # ── Defense & Aerospace ──────────────────────────────────────────────
    RSSSource("Defense News",          "https://www.defensenews.com/rss/",                                 ["defense"], weight=1.2),
    RSSSource("Breaking Defense",      "https://breakingdefense.com/feed/",                                ["defense"], weight=1.2),
    RSSSource("Aviation Week",         "https://aviationweek.com/rss.xml",                                 ["defense"]),

    # ── Real Estate ──────────────────────────────────────────────────────
    RSSSource("CoStar News",           "https://www.costar.com/rss/news",                                  ["real_estate"]),
    RSSSource("Bisnow",                "https://www.bisnow.com/rss",                                       ["real_estate"]),

    # ── Consumer & Retail ────────────────────────────────────────────────
    RSSSource("Retail Dive",           "https://www.retaildive.com/feeds/news/",                           ["consumer"], weight=1.1),
    RSSSource("Chain Store Age",       "https://chainstoreage.com/rss.xml",                                ["consumer"]),
]

# ---------------------------------------------------------------------------
# NewsAPI.org configuration  (requires free API key from newsapi.org)
# ---------------------------------------------------------------------------
NEWSAPI_ENDPOINTS = {
    "top_headlines": "https://newsapi.org/v2/top-headlines",
    "everything":    "https://newsapi.org/v2/everything",
}

NEWSAPI_QUERIES = {
    "technology":          "technology OR semiconductor OR software",
    "artificial_intelligence": "artificial intelligence OR machine learning OR LLM OR generative AI",
    "financial_services":  "banking OR fintech OR investment OR hedge fund",
    "energy":              "oil OR natural gas OR renewable energy OR solar",
    "healthcare":          "biotech OR pharma OR FDA OR clinical trial",
    "crypto":              "Bitcoin OR Ethereum OR DeFi OR blockchain",
    "macro":               "Federal Reserve OR inflation OR GDP OR interest rates",
    "defense":             "defense contract OR military OR aerospace",
    "real_estate":         "real estate OR REIT OR housing market",
    "consumer":            "retail OR consumer spending OR e-commerce",
    "commodities":         "gold OR copper OR wheat OR commodity",
}

# ---------------------------------------------------------------------------
# Finnhub configuration  (requires free API key from finnhub.io)
# ---------------------------------------------------------------------------
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"
FINNHUB_CATEGORIES = ["general", "forex", "crypto", "merger"]  # free-tier

# ---------------------------------------------------------------------------
# Alpha Vantage news  (requires free API key from alphavantage.co)
# ---------------------------------------------------------------------------
ALPHA_VANTAGE_NEWS_URL = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_TICKERS_BY_SECTOR = {
    "technology":          ["AAPL", "MSFT", "NVDA", "META", "GOOGL"],
    "artificial_intelligence": ["NVDA", "MSFT", "GOOGL", "AMZN", "PLTR"],
    "financial_services":  ["JPM", "GS", "BAC", "V", "MA"],
    "energy":              ["XOM", "CVX", "OXY", "NEE", "ENPH"],
    "healthcare":          ["JNJ", "PFE", "ABBV", "UNH", "MRNA"],
    "crypto":              ["COIN", "MSTR", "MARA", "RIOT"],
    "defense":             ["LMT", "RTX", "NOC", "GD"],
    "real_estate":         ["AMT", "PLD", "EQIX", "SPG"],
    "consumer":            ["AMZN", "TSLA", "WMT", "COST"],
    "commodities":         ["GLD", "SLV", "USO", "CORN"],
}
