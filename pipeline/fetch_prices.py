"""
fetch_prices.py

For each unique ticker in trades.csv (plus SPY as benchmark), fetches daily
adjusted close prices via yfinance over the full date range needed.

Caches per-ticker CSVs in data/prices/ — skips fetch if cache already exists.
Handles delisted/invalid tickers gracefully (logs warning, skips).

Outputs: data/prices/<TICKER>.csv  (columns: date, close)
"""

import time
import os
import pandas as pd
import yfinance as yf
from datetime import timedelta

TRADES_PATH = "data/trades.csv"
PRICES_DIR  = "data/prices"
BENCHMARK   = "SPY"
FETCH_SLEEP = 0.5  # seconds between yfinance calls


def load_tickers_and_date_range(trades_path: str) -> tuple:
    """
    Returns (tickers, start_date, end_date) derived from trades.csv.
    Date range: earliest transaction date → today + 1 day (to cover 1-year windows).
    """
    df = pd.read_csv(trades_path, parse_dates=["date"])
    tickers = sorted(df["ticker"].dropna().unique().tolist())

    start_date = df["date"].min() - timedelta(days=5)  # small buffer for weekends
    end_date   = pd.Timestamp.today().normalize() + timedelta(days=1)

    return tickers, start_date, end_date


def fetch_ticker(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """
    Downloads daily adjusted close for a single ticker via yfinance.
    Returns DataFrame with columns [date, close], or empty DataFrame on failure.
    """
    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if raw.empty:
            print(f"  [WARN] No data returned for {ticker} — may be delisted or invalid.")
            return pd.DataFrame(columns=["date", "close"])

        df = raw[["Close"]].copy()
        df.columns = ["close"]
        df.index.name = "date"
        df = df.reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
        return df

    except Exception as e:
        print(f"  [WARN] Failed to fetch {ticker}: {e}")
        return pd.DataFrame(columns=["date", "close"])


def fetch_all_prices(tickers: list, start: pd.Timestamp, end: pd.Timestamp, prices_dir: str):
    """
    Fetches prices for all tickers + benchmark. Skips if cache CSV already exists.
    """
    os.makedirs(prices_dir, exist_ok=True)
    all_tickers = sorted(set(tickers + [BENCHMARK]))

    for i, ticker in enumerate(all_tickers):
        cache_path = os.path.join(prices_dir, f"{ticker}.csv")

        if os.path.exists(cache_path):
            print(f"  [{i+1}/{len(all_tickers)}] {ticker} — cached, skipping.")
            continue

        print(f"  [{i+1}/{len(all_tickers)}] {ticker} — fetching...")
        df = fetch_ticker(ticker, start, end)

        if not df.empty:
            df.to_csv(cache_path, index=False)

        time.sleep(FETCH_SLEEP)


def load_price_series(ticker: str, prices_dir: str = PRICES_DIR) -> pd.DataFrame:
    """
    Loads a cached price CSV for a ticker. Returns empty DataFrame if not found.
    Used by downstream scripts (calculate_alpha.py).
    """
    path = os.path.join(prices_dir, f"{ticker}.csv")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date", "close"])
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def get_price_on_or_after(ticker: str, target_date: pd.Timestamp, prices_dir: str = PRICES_DIR):
    """
    Returns the close price on target_date, or the next available trading day.
    Returns None if no price is found within 5 trading days.
    Used by calculate_alpha.py.
    """
    df = load_price_series(ticker, prices_dir)
    if df.empty:
        return None

    candidates = df[df["date"] >= target_date]
    if candidates.empty:
        return None

    # Allow up to 5 calendar days forward to skip weekends/holidays
    closest = candidates.iloc[0]
    if (closest["date"] - target_date).days > 5:
        return None

    return float(closest["close"])


def main():
    print(f"Loading tickers from {TRADES_PATH}...")
    tickers, start, end = load_tickers_and_date_range(TRADES_PATH)
    print(f"  {len(tickers)} unique tickers | range: {start.date()} → {end.date()}")

    fetch_all_prices(tickers, start, end, PRICES_DIR)
    print(f"\nDone. Prices cached in {PRICES_DIR}/")


if __name__ == "__main__":
    main()
