"""
build_hierarchy.py

Assembles hierarchy.json for the D3 sunburst from trades.csv + alphas.csv.

Structure:
  Congress (root)
    └── Party             (inner ring)
          └── Politician  (middle ring) — sized by total volume, colored by weighted_alpha
                └── Ticker              (outer ring) — sized by volume for that ticker
                └── "N others"          (collapsed if politician has > MAX_TICKERS tickers)

How many tickers are visible vs collapsed in the *chart* is decided in the frontend
(App.tsx collapseSmallTickers) based on the actual rendered chart size.  The pipeline
only caps at MAX_TICKERS (enough to supply the zoom view) and stores the rest in
collapsed_tickers for the side panel.

Outputs: public/hierarchy.json
"""

import json
import math
import os
import numpy as np
import pandas as pd

TRADES_PATH        = "data/trades.csv"
ALPHAS_PATH        = "data/alphas.csv"
TICKER_ALPHAS_PATH = "data/ticker_alphas.csv"
OUTPUT_PATH        = "public/hierarchy.json"
LEGISLATORS_PATH   = "pipeline/data/raw/legislators-current.csv"

# Max tickers stored directly in children.
# Must be >= App.tsx ZOOM_MAX_TICKERS (≈ 157) so the zoom view can fully expand.
MAX_TICKERS = 200

# Canonical party display order in the sunburst (clockwise)
PARTY_ORDER = ["Democratic", "Republican", "Independent", "Other"]


def load_current_legislators(path: str) -> set:
    """
    Returns a set of normalized full names of currently serving legislators.
    Falls back to empty set (all politicians treated as current) if file not found.
    """
    if not os.path.exists(path):
        print(f"  [WARN] {path} not found — is_current will be False for all politicians.")
        return set()
    df = pd.read_csv(path, usecols=["full_name"])
    return set(df["full_name"].str.strip().str.lower())


def build_ticker_nodes(ticker_volumes: pd.Series, ticker_alphas: pd.Series) -> list:
    """
    Given a Series of {ticker: volume} and a Series of {ticker: alpha}, returns leaf nodes.
    Stores the top MAX_TICKERS tickers directly; the rest are collapsed into "N others"
    for the side panel.  The frontend (App.tsx collapseSmallTickers) decides how many
    of the top-MAX_TICKERS tickers are actually visible in the chart ring.
    """
    total = ticker_volumes.sum()
    if total == 0:
        return []

    ticker_volumes = ticker_volumes.sort_values(ascending=False)

    visible   = ticker_volumes.head(MAX_TICKERS)
    collapsed = ticker_volumes.iloc[MAX_TICKERS:]

    def ticker_node(ticker, volume):
        alpha = ticker_alphas.get(ticker)
        node = {"name": ticker, "value": int(volume)}
        if alpha is not None and not math.isnan(alpha):
            node["alpha"] = round(float(alpha), 4)
        return node

    nodes = [ticker_node(ticker, volume) for ticker, volume in visible.items()]

    if len(collapsed) == 1:
        nodes.append(ticker_node(collapsed.index[0], collapsed.iloc[0]))
    elif not collapsed.empty:
        nodes.append({
            "name": f"{len(collapsed)} others",
            "value": int(collapsed.sum()),
            "collapsed": True,
            "collapsed_tickers": [
                ticker_node(t, v)
                for t, v in collapsed.sort_values(ascending=False).items()
            ],
        })

    return nodes


def build_politician_node(politician: str, alpha_row: pd.Series, trades: pd.DataFrame,
                          current_legislators: set, pol_ticker_alphas: pd.Series) -> dict:
    """
    Builds a politician node with ticker children.
    Ticker volumes = sum of amount_mid for ALL trades (buy + sell) for that ticker.
    pol_ticker_alphas: Series indexed by ticker with per-ticker weighted alpha for this politician.
    """
    ticker_volumes = trades.groupby("ticker")["amount_mid"].sum()
    ticker_nodes   = build_ticker_nodes(ticker_volumes, pol_ticker_alphas)

    node = {
        "name":           politician,
        "party_code":     alpha_row["party"][0] if alpha_row["party"] else "?",
        "weighted_alpha": None if np.isnan(alpha_row["weighted_alpha"]) else round(float(alpha_row["weighted_alpha"]), 4),
        "total_volume":   int(alpha_row["total_volume"]),
        "trade_count":    int(alpha_row["trade_count"]),
        "is_current":     politician.strip().lower() in current_legislators,
        "children":       ticker_nodes,
    }
    return node


def build_party_node(party: str, politicians_df: pd.DataFrame, trades: pd.DataFrame,
                     current_legislators: set, ticker_alphas_df: pd.DataFrame) -> dict:
    """
    Builds a party node with politician children, sorted by weighted_alpha descending.
    Politicians with NaN alpha are sorted to the end.
    """
    party_politicians = politicians_df[politicians_df["party"] == party].copy()

    party_politicians["_sort_key"] = party_politicians["weighted_alpha"].where(
        party_politicians["weighted_alpha"].notna(), other=-np.inf
    )
    party_politicians = party_politicians.sort_values("_sort_key", ascending=False)

    children = []
    for _, alpha_row in party_politicians.iterrows():
        politician = alpha_row["politician"]
        politician_trades = trades[trades["politician"] == politician]
        if politician_trades.empty:
            continue
        pol_ticker_alphas = (
            ticker_alphas_df[ticker_alphas_df["politician"] == politician]
            .set_index("ticker")["weighted_alpha"]
        )
        node = build_politician_node(
            politician, alpha_row, politician_trades, current_legislators, pol_ticker_alphas
        )
        children.append(node)

    return {
        "name":     party,
        "children": children,
    }


def build_hierarchy(alphas: pd.DataFrame, trades: pd.DataFrame,
                    current_legislators: set, ticker_alphas_df: pd.DataFrame) -> dict:
    """
    Builds the full 3-layer hierarchy dict.
    Only includes parties that have at least one politician with trade data.
    """
    present_parties = alphas["party"].unique()
    ordered_parties = [p for p in PARTY_ORDER if p in present_parties]
    ordered_parties += [p for p in present_parties if p not in ordered_parties]

    party_nodes = []
    for party in ordered_parties:
        node = build_party_node(party, alphas, trades, current_legislators, ticker_alphas_df)
        if node["children"]:
            party_nodes.append(node)

    return {
        "name":     "Congress",
        "children": party_nodes,
    }


def main():
    os.makedirs("public", exist_ok=True)

    print(f"Loading {TRADES_PATH}...")
    trades = pd.read_csv(TRADES_PATH, parse_dates=["date"])

    print(f"Loading {ALPHAS_PATH}...")
    alphas = pd.read_csv(ALPHAS_PATH)

    print(f"Loading {TICKER_ALPHAS_PATH}...")
    ticker_alphas_df = pd.read_csv(TICKER_ALPHAS_PATH)

    print(f"Loading current legislators from {LEGISLATORS_PATH}...")
    current_legislators = load_current_legislators(LEGISLATORS_PATH)

    print(f"  {len(alphas)} politicians across parties: {alphas['party'].value_counts().to_dict()}")

    current_count = sum(1 for n in alphas["politician"] if n.strip().lower() in current_legislators)
    print(f"  Currently serving matched: {current_count}/{len(alphas)}")

    hierarchy = build_hierarchy(alphas, trades, current_legislators, ticker_alphas_df)

    total_politicians = sum(len(p["children"]) for p in hierarchy["children"])
    print(f"  Built hierarchy: {len(hierarchy['children'])} parties, {total_politicians} politicians")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(hierarchy, f, indent=2)
    print(f"  Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
