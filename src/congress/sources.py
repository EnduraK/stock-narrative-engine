"""
Congress trade data sources and high-value politician watchlists.

Data comes from free public STOCK Act disclosure aggregators.
No API key required for any primary source.

Source reliability notes (as of 2026):
  - house-stock-watcher S3: blocks cloud/VPS IPs (403)
  - senate-stock-watcher S3: blocks cloud/VPS IPs (403)
  - quiverquant.com: now requires paid API key (401)
  - GitHub jeremybernier mirror: stale / 404
  PRIMARY: CapitolTrades JSON API — works from server IPs, no auth
  FALLBACK: StockSear public API — free, no auth
"""

# ---------------------------------------------------------------------------
# Free public data endpoints — ordered by reliability from VPS/cloud IPs
# ---------------------------------------------------------------------------

# PRIMARY (House + Senate combined): CapitolTrades public JSON API
# Returns paginated list of trades; page/pageSize query params supported.
# No auth required, works reliably from server IPs.
CAPITOLTRADES_API_URL = (
    "https://www.capitoltrades.com/api/trades"
    "?page=1&pageSize=250&chamber=house,senate"
)

CAPITOLTRADES_API_SENATE = (
    "https://www.capitoltrades.com/api/trades"
    "?page=1&pageSize=250&chamber=senate"
)

# FALLBACK: StockSear free API — no auth, works from cloud IPs
STOCKSEAR_HOUSE_URL = (
    "https://stocksear.com/api/v1/politicians"
    "?type=congress&chamber=house&limit=200"
)
STOCKSEAR_SENATE_URL = (
    "https://stocksear.com/api/v1/politicians"
    "?type=congress&chamber=senate&limit=200"
)

# LAST RESORT: House/Senate S3 (may 403 from cloud IPs, but worth trying)
HOUSE_S3_FALLBACK = (
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com"
    "/data/all_transactions.json"
)
SENATE_S3_FALLBACK = (
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com"
    "/aggregate/all_transactions.json"
)

# Aliases used by fetcher.py (kept for backward compat)
HOUSE_TRANSACTIONS_URL   = CAPITOLTRADES_API_URL
SENATE_TRANSACTIONS_URL  = CAPITOLTRADES_API_SENATE


# ---------------------------------------------------------------------------
# High-value politician watchlist
# Politicians selected for consistent market-beating performance,
# seniority/committee positions, or notable sector-specific influence.
# ---------------------------------------------------------------------------
HIGH_VALUE_POLITICIANS = {
    # ── House ──────────────────────────────────────────────────────────
    "Nancy Pelosi": {
        "chamber": "house",
        "party": "Democrat",
        "known_sectors": ["technology", "artificial_intelligence", "consumer"],
        "notes": "Historically strong tech performance; husband Paul Pelosi active trader",
        "weight": 2.0,
    },
    "Michael McCaul": {
        "chamber": "house",
        "party": "Republican",
        "known_sectors": ["technology", "defense"],
        "notes": "House Foreign Affairs Committee; tech and defense exposure",
        "weight": 1.6,
    },
    "Josh Gottheimer": {
        "chamber": "house",
        "party": "Democrat",
        "known_sectors": ["technology", "financial_services"],
        "notes": "Financial services committee; frequent trader",
        "weight": 1.5,
    },
    "Marjorie Taylor Greene": {
        "chamber": "house",
        "party": "Republican",
        "known_sectors": ["energy", "technology"],
        "notes": "Frequent disclosure filer",
        "weight": 1.3,
    },
    "Dan Crenshaw": {
        "chamber": "house",
        "party": "Republican",
        "known_sectors": ["energy", "defense"],
        "notes": "Energy & Commerce Committee",
        "weight": 1.4,
    },
    "Ro Khanna": {
        "chamber": "house",
        "party": "Democrat",
        "known_sectors": ["technology", "artificial_intelligence"],
        "notes": "Silicon Valley district; tech sector insider knowledge",
        "weight": 1.5,
    },

    # ── Senate ──────────────────────────────────────────────────────────
    "Mark Warner": {
        "chamber": "senate",
        "party": "Democrat",
        "known_sectors": ["technology", "financial_services"],
        "notes": "Senate Intelligence Committee; former tech entrepreneur",
        "weight": 1.8,
    },
    "Tommy Tuberville": {
        "chamber": "senate",
        "party": "Republican",
        "known_sectors": ["commodities", "energy", "financial_services"],
        "notes": "Armed Services Committee; very active trader",
        "weight": 1.7,
    },
    "Sheldon Whitehouse": {
        "chamber": "senate",
        "party": "Democrat",
        "known_sectors": ["energy", "healthcare"],
        "notes": "Environment & Public Works Committee",
        "weight": 1.4,
    },
    "John Hoeven": {
        "chamber": "senate",
        "party": "Republican",
        "known_sectors": ["energy", "commodities"],
        "notes": "Energy & Natural Resources Committee",
        "weight": 1.4,
    },
    "Bill Hagerty": {
        "chamber": "senate",
        "party": "Republican",
        "known_sectors": ["financial_services", "technology"],
        "notes": "Banking Committee; former ambassador to Japan",
        "weight": 1.5,
    },
    "Mitt Romney": {
        "chamber": "senate",
        "party": "Republican",
        "known_sectors": ["financial_services", "consumer", "technology"],
        "notes": "Former private equity; broad portfolio",
        "weight": 1.6,
    },
}

# ---------------------------------------------------------------------------
# Ticker → sector mapping for cross-referencing trades
# (extends the main market/sectors.py with more granular coverage)
# ---------------------------------------------------------------------------
TICKER_SECTOR_MAP = {
    # Technology
    "AAPL": "technology", "MSFT": "technology", "GOOGL": "technology",
    "GOOG": "technology", "META": "technology", "AMZN": "technology",
    "TSLA": "technology", "NVDA": "artificial_intelligence",
    "AMD": "artificial_intelligence", "INTC": "technology",
    "CRM": "technology", "ORCL": "technology", "IBM": "technology",
    "CSCO": "technology", "QCOM": "technology", "AVGO": "artificial_intelligence",
    "PLTR": "artificial_intelligence", "AI": "artificial_intelligence",
    # Financial services
    "JPM": "financial_services", "GS": "financial_services",
    "BAC": "financial_services", "WFC": "financial_services",
    "MS": "financial_services", "BLK": "financial_services",
    "V": "financial_services", "MA": "financial_services",
    "AXP": "financial_services", "SCHW": "financial_services",
    # Healthcare
    "JNJ": "healthcare", "PFE": "healthcare", "ABBV": "healthcare",
    "MRK": "healthcare", "LLY": "healthcare", "UNH": "healthcare",
    "MRNA": "healthcare", "AMGN": "healthcare", "ISRG": "healthcare",
    "CVS": "healthcare", "TMO": "healthcare",
    # Energy
    "XOM": "energy", "CVX": "energy", "COP": "energy",
    "SLB": "energy", "EOG": "energy", "OXY": "energy",
    "NEE": "energy", "ENPH": "energy", "FSLR": "energy",
    # Defense
    "LMT": "defense", "RTX": "defense", "NOC": "defense",
    "GD": "defense", "BA": "defense", "LHX": "defense",
    # Consumer
    "WMT": "consumer",  "COST": "consumer", "TGT": "consumer",
    "NKE": "consumer", "SBUX": "consumer", "MCD": "consumer",
    "HD": "consumer", "LOW": "consumer",
    # Real estate
    "AMT": "real_estate", "PLD": "real_estate", "EQIX": "real_estate",
    "SPG": "real_estate", "O": "real_estate",
    # Crypto
    "COIN": "crypto", "MSTR": "crypto", "MARA": "crypto", "RIOT": "crypto",
    # Commodities
    "GLD": "commodities", "SLV": "commodities", "USO": "commodities",
}
