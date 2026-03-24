"""
fetch_trades.py

Loads congressional stock transactions from a local Kaggle CSV dataset.
Source: "Congress Trading All" dataset (placed in pipeline/data/raw/).
Parses amount ranges into numeric midpoints.
Filters to politicians with 10+ purchase transactions (active traders).
Outputs: data/trades.csv
"""

import glob
import os
import pandas as pd

RAW_DATA_DIR = "pipeline/data/raw"

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

# Kaggle CSV column → our canonical column name
COLUMN_MAP = {
    "Name":           "politician",
    "Party":          "party",
    "Chamber":        "chamber",
    "Ticker":         "ticker",
    "Transaction":    "type",
    "Traded":         "date",
    "Trade_Size_USD": "amount_str",
}


def find_raw_csv(raw_dir: str) -> str:
    """Returns path to the first CSV found in raw_dir, or raises if none found."""
    csvs = glob.glob(os.path.join(raw_dir, "*.csv"))
    if not csvs:
        raise FileNotFoundError(
            f"No CSV found in {raw_dir}. "
            "Please download the Kaggle 'congress-trading-all' dataset and place it there."
        )
    return csvs[0]


def load_raw(raw_dir: str) -> pd.DataFrame:
    path = find_raw_csv(raw_dir)
    print(f"  Loading {path}...")
    df = pd.read_csv(path, usecols=list(COLUMN_MAP.keys()), encoding="latin-1")
    df = df.rename(columns=COLUMN_MAP)
    return df


def parse_amount(amount_str: str):
    """Return numeric midpoint for a disclosed amount range, or None if unrecognized."""
    if not isinstance(amount_str, str):
        return None
    return AMOUNT_MIDPOINTS.get(amount_str.strip(), None)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Parse amount to numeric midpoint
    df["amount_mid"] = df["amount_str"].apply(parse_amount)

    # Drop rows with no usable amount or ticker
    df = df[df["amount_mid"].notna()].copy()
    df = df[df["ticker"].notna()].copy()
    df = df[df["ticker"].str.len() > 0].copy()
    df = df[~df["ticker"].isin(["", "--", "N/A"])].copy()

    # Keep only valid equity tickers: 1-5 uppercase letters only
    # Filters out bond CUSIPs (e.g. 912796WX3), options, and other non-equity instruments
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}$")].copy()

    # Normalize transaction type to lowercase
    df["type"] = df["type"].str.strip().str.lower()

    # Parse date (Kaggle format: "Monday, March 11, 2024")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()].copy()

    # Normalize politician names — strip honorifics that appear inconsistently in the dataset
    honorifics = r"\b(Dr|Hon|Mr|Mrs|Ms|Jr|Sr|II|III|IV)\b\.?\s*"
    df["politician"] = (
        df["politician"]
        .str.replace(honorifics, " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    # Normalize party and chamber
    df["party"]   = df["party"].str.strip()
    df["chamber"] = df["chamber"].str.strip()

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

    df = load_raw(RAW_DATA_DIR)
    print(f"  Raw rows: {len(df)}")

    cleaned = clean(df)
    print(f"  After cleaning: {len(cleaned)}")

    active = filter_active_traders(cleaned)
    print(f"  Rows for active traders: {len(active)}")

    out_path = "data/trades.csv"
    active.to_csv(out_path, index=False)
    print(f"  Saved → {out_path}")


if __name__ == "__main__":
    main()
