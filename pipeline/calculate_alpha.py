"""
calculate_alpha.py

For each purchase transaction in trades.csv, computes:
  alpha_i = stock_return - SPY_return  over a fixed 1-year window from purchase date
            (uses today's price as end if purchase < 1 year ago)

Aggregates to weighted alpha per politician:
  weighted_alpha = sum(alpha_i * amount_mid_i) / sum(amount_mid_i)  [purchases only]

Also computes total_volume (all trades) and trade_count (all trades) per politician.

Outputs: data/alphas.csv
  columns: politician, party, weighted_alpha, total_volume, trade_count
"""

import pandas as pd
import numpy as np
import os
from datetime import timedelta
from fetch_prices import get_price_on_or_after, BENCHMARK

TRADES_PATH = "data/trades.csv"
ALPHAS_PATH = "data/alphas.csv"
PRICES_DIR  = "data/prices"

ALPHA_WINDOW_DAYS = 365

# Party name normalization → canonical display names for the sunburst
PARTY_NORMALIZATION = {
    "democrat":      "Democratic",
    "democratic":    "Democratic",
    "d":             "Democratic",
    "republican":    "Republican",
    "r":             "Republican",
    "independent":   "Independent",
    "i":             "Independent",
}


def normalize_party(party_str: str) -> str:
    if not isinstance(party_str, str):
        return "Other"
    return PARTY_NORMALIZATION.get(party_str.strip().lower(), "Other")


def compute_return(start_price, end_price) -> float:
    """Simple price return: (end - start) / start."""
    if start_price is None or end_price is None:
        return None
    if start_price == 0:
        return None
    return (end_price - start_price) / start_price


def compute_alpha_for_purchase(row: pd.Series, today: pd.Timestamp, prices_dir: str):
    """
    Computes alpha for a single purchase row.
    Returns float alpha or None if prices unavailable.
    """
    purchase_date = row["date"]
    end_date = min(purchase_date + timedelta(days=ALPHA_WINDOW_DAYS), today)

    stock_start = get_price_on_or_after(row["ticker"], purchase_date, prices_dir)
    stock_end   = get_price_on_or_after(row["ticker"], end_date, prices_dir)
    spy_start   = get_price_on_or_after(BENCHMARK, purchase_date, prices_dir)
    spy_end     = get_price_on_or_after(BENCHMARK, end_date, prices_dir)

    stock_return = compute_return(stock_start, stock_end)
    spy_return   = compute_return(spy_start, spy_end)

    if stock_return is None or spy_return is None:
        return None

    return stock_return - spy_return


def compute_alphas(trades: pd.DataFrame, today: pd.Timestamp, prices_dir: str) -> pd.DataFrame:
    """
    Adds alpha_i column to purchase rows. Non-purchase rows get NaN.
    """
    trades = trades.copy()
    trades["alpha"] = np.nan

    purchases_mask = trades["type"] == "purchase"
    purchases = trades[purchases_mask]

    alphas = purchases.apply(
        lambda row: compute_alpha_for_purchase(row, today, prices_dir), axis=1
    )
    trades.loc[purchases_mask, "alpha"] = alphas
    return trades


def aggregate_by_politician(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates per-politician metrics:
      - weighted_alpha: purchase-weighted alpha (purchases with valid alpha only)
      - total_volume:   sum of amount_mid for ALL trades
      - trade_count:    number of ALL trade rows
      - party:          most common normalized party label
    """
    trades = trades.copy()
    trades["party"] = trades["party"].apply(normalize_party)

    rows = []
    for politician, group in trades.groupby("politician"):
        party = group["party"].mode().iloc[0]
        total_volume = group["amount_mid"].sum()
        trade_count  = len(group)

        purchases_with_alpha = group[
            (group["type"] == "purchase") & group["alpha"].notna()
        ]

        if purchases_with_alpha.empty:
            weighted_alpha = np.nan
        else:
            weights = purchases_with_alpha["amount_mid"]
            weighted_alpha = (
                (purchases_with_alpha["alpha"] * weights).sum() / weights.sum()
            )

        rows.append({
            "politician":     politician,
            "party":          party,
            "weighted_alpha": weighted_alpha,
            "total_volume":   total_volume,
            "trade_count":    trade_count,
        })

    return pd.DataFrame(rows)


def main():
    os.makedirs("data", exist_ok=True)
    today = pd.Timestamp.today().normalize()

    print(f"Loading trades from {TRADES_PATH}...")
    trades = pd.read_csv(TRADES_PATH, parse_dates=["date"])
    print(f"  {len(trades)} rows, {trades['politician'].nunique()} politicians")

    print("Computing per-purchase alpha...")
    trades_with_alpha = compute_alphas(trades, today, PRICES_DIR)

    valid = trades_with_alpha["alpha"].notna().sum()
    total_purchases = (trades_with_alpha["type"] == "purchase").sum()
    print(f"  Alpha computed for {valid}/{total_purchases} purchases")

    print("Aggregating by politician...")
    alphas = aggregate_by_politician(trades_with_alpha)
    print(f"  {len(alphas)} politicians")

    alphas.to_csv(ALPHAS_PATH, index=False)
    print(f"  Saved → {ALPHAS_PATH}")


if __name__ == "__main__":
    main()
