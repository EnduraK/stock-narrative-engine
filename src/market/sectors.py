"""
Sector definitions: canonical ticker lists and ETF proxies for each sector.
Used by the market data layer to pull price/momentum context.
"""

from typing import Dict, List

# Representative stocks per sector (used for price context)
SECTOR_TICKERS: Dict[str, List[str]] = {
    "technology":              ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSM", "AVGO"],
    "artificial_intelligence": ["NVDA", "MSFT", "GOOGL", "AMZN", "PLTR", "AI", "PATH", "SOUN"],
    "financial_services":      ["JPM", "GS", "BAC", "V", "MA", "BRK-B", "SCHW", "BLK"],
    "energy":                  ["XOM", "CVX", "OXY", "SLB", "EOG", "NEE", "ENPH", "FSLR"],
    "healthcare":              ["JNJ", "PFE", "ABBV", "UNH", "MRNA", "LLY", "AMGN", "ISRG"],
    "consumer":                ["AMZN", "TSLA", "WMT", "COST", "TGT", "NKE", "SBUX", "MCD"],
    "real_estate":             ["AMT", "PLD", "EQIX", "SPG", "O", "DLR", "PSA", "WELL"],
    "crypto":                  ["COIN", "MSTR", "MARA", "RIOT", "CLSK"],
    "defense":                 ["LMT", "RTX", "NOC", "GD", "BA", "L3H"],
    "commodities":             ["GLD", "SLV", "USO", "CORN", "WEAT", "CPER"],
    "macro":                   ["SPY", "QQQ", "DIA", "IWM", "TLT", "GLD", "DXY"],
}

# Sector ETFs for quick macro reads
SECTOR_ETFS: Dict[str, str] = {
    "technology":              "XLK",
    "financial_services":      "XLF",
    "energy":                  "XLE",
    "healthcare":              "XLV",
    "consumer":                "XLY",
    "real_estate":             "XLRE",
    "defense":                 "ITA",
    "commodities":             "PDBC",
    "artificial_intelligence": "BOTZ",
    "crypto":                  "BITO",
    "macro":                   "SPY",
}

# Human-friendly labels for display
SECTOR_LABELS: Dict[str, str] = {
    "technology":              "Technology",
    "artificial_intelligence": "Artificial Intelligence",
    "financial_services":      "Financial Services",
    "energy":                  "Energy",
    "healthcare":              "Healthcare & Biotech",
    "consumer":                "Consumer & Retail",
    "real_estate":             "Real Estate",
    "crypto":                  "Crypto & Web3",
    "defense":                 "Defense & Aerospace",
    "commodities":             "Commodities",
    "macro":                   "Macro / Broad Market",
}
