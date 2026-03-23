"""
fetch_trades.py

Pulls all congressional stock transactions from House + Senate Stock Watcher (S3).
Parses amount ranges into numeric midpoints.
Filters to politicians with 10+ purchase transactions (active traders).
Outputs: data/trades.csv
"""

import requests
import pandas as pd
import os

HOUSE_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

# Agreed midpoints for disclosed amount ranges.
# $1M+ open-ended cap: using $2,500,000 as midpoint (documented choice).
AMOUNT_MIDPOINTS = {
    "$1,001 - $15,000":         8_000,
    "$15,001 - $50,000":        32_500,
    "$50,001 - $100,000":       75_000,
    "$100,001 - $250,000":      175_000,
    "$250,001 - $500,000":      375_000,
    "$500,001 - $1,000,000":    750_000,
    "$1,000,001 - $5,000,000":  2_500_000,
    "$5,000,001 - $25,000,000": 15_000_000,
    "$25,000,001 - $50,000,000":37_500_000,
}

MIN_PURCHASE_TRANSACTIONS = 10


def parse_amount(amount_str: str):
    """Return numeric midpoint for a disclosed amount range, or None if unrecognized."""
    if not isinstance(amount_str, str):
        return None
    cleaned = amount_str.strip()
    return AMOUNT_MIDPOINTS.get(cleaned, None)


def fetch_house() -> pd.DataFrame:
    print("Fetching House trades...")
    resp = requests.get(HOUSE_URL, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for t in raw:
        rows.append({
            "politician": t.get("representative", "").strip(),
            "party":      t.get("party", "").strip(),
            "chamber":    "House",
            "ticker":     t.get("ticker", "").strip().upper(),
            "type":       t.get("type", "").strip().lower(),
            "date":       t.get("transaction_date", "").strip(),
            "amount_str": t.get("amount", ""),
        })

    return pd.DataFrame(rows)


def fetch_senate() -> pd.DataFrame:
    print("Fetching Senate trades...")
    resp = requests.get(SENATE_URL, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    rows = []
    for t in raw:
        rows.append({
            "politician": t.get("senator", "").strip(),
            "party":      t.get("party", "").strip(),
            "chamber":    "Senate",
            "ticker":     t.get("ticker", "").strip().upper(),
            "type":       t.get("type", "").strip().lower(),
            "date":       t.get("transaction_date", "").strip(),
            "amount_str": t.get("amount", ""),
        })

    return pd.DataFrame(rows)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Parse amount to numeric midpoint
    df["amount_mid"] = df["amount_str"].apply(parse_amount)

    # Drop rows with no usable amount or ticker
    df = df[df["amount_mid"].notna()].copy()
    df = df[df["ticker"].str.len() > 0].copy()

    # Drop non-stock rows (options, bonds, etc. often have no clean ticker)
    df = df[~df["ticker"].isin(["", "--", "N/A"])].copy()

    # Normalize transaction type
    df["type"] = df["type"].str.lower()

    # Parse date
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()].copy()

    return df


def filter_active_traders(df: pd.DataFrame) -> pd.DataFrame:
    purchases = df[df["type"] == "purchase"]
    purchase_counts = purchases.groupby("politician").size()
    active = purchase_counts[purchase_counts >= MIN_PURCHASE_TRANSACTIONS].index
    filtered = df[df["politician"].isin(active)].copy()

    print(f"  Active traders (>= {MIN_PURCHASE_TRANSACTIONS} purchases): {len(active)}")
    return filtered


def main():
    os.makedirs("data", exist_ok=True)

    house = fetch_house()
    senate = fetch_senate()
    combined = pd.concat([house, senate], ignore_index=True)

    print(f"  Raw rows: {len(combined)}")

    cleaned = clean(combined)
    print(f"  After cleaning: {len(cleaned)}")

    active = filter_active_traders(cleaned)
    print(f"  Rows for active traders: {len(active)}")

    out_path = "data/trades.csv"
    active.to_csv(out_path, index=False)
    print(f"  Saved → {out_path}")


if __name__ == "__main__":
    main()
