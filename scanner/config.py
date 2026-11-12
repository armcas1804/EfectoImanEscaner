"""Configuration for the independent Efecto Imán scanner."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("EFECTO_SCANNER_DATA", str(BASE_DIR / "data"))).resolve()
DATABASE_PATH = DATA_DIR / "scanner.db"
SCORE_VERSION = "home-b-approved-2026-11-11"
CUTS = (10, 30, 60, 90)

TICKERS = (
    "AMZN", "AAPL", "GOOG", "META", "MSFT", "NFLX", "TSLA", "PLTR", "ORCL",
    "AMD", "MU", "NVDA", "QCOM", "AVGO", "SOXL", "DASH", "LYFT", "UBER",
    "HD", "LOW", "WMT", "DIA", "QQQ", "SPY", "SPX", "IWM", "TNA", "AXP",
    "C", "MA", "PYPL", "V", "BABA", "LI", "NIO", "XPEV", "GLD", "SLV",
    "USO", "COIN", "HOOD", "CVS", "MRNA", "PFE", "BA", "URA", "CCL",
    "RCL", "AAL", "DAL", "TZA",
    "JNJ", "DIS", "MRVL", "IBM", "JPM", "XOM", "CAT", "SBUX", "VZ",
    "T", "MCD", "NKE", "KO", "SCHW", "COST", "DELL", "WFC", "ANET",
    "PG", "CVX", "MRK",
)
PROVIDER_SYMBOLS = {"SPX": "^GSPC"}
