"""
build_hierarchy.py

Assembles hierarchy.json for the D3 sunburst from trades.csv + alphas.csv.

Structure:
  Congress (root)
    └── Party             (inner ring)
          └── Politician  (middle ring) — sized by total volume, colored by weighted_alpha
                └── Ticker              (outer ring) — sized by volume for that ticker
                └── "N others"          (collapsed if ticker < MIN_TICKER_FRACTION of politician volume)

Outputs: public/hierarchy.json
"""

import json
import os
import numpy as np
import pandas as pd

TRADES_PATH  = "data/trades.csv"
ALPHAS_PATH  = "data/alphas.csv"
OUTPUT_PATH  = "public/hierarchy.json"

# Tickers representing < this fraction of a politician's total volume get collapsed.
# Approximates the ~0.015 radian arc-width threshold; tune empirically after rendering.
MIN_TICKER_FRACTION = 0.03

# Canonical party display order in the sunburst (clockwise)
PARTY_ORDER = ["Democratic", "Republican", "Independent", "Other"]


def build_ticker_nodes(ticker_volumes: pd.Series, min_fraction: float) -> list:
    """
    Given a Series of {ticker: volume}, returns a list of leaf nodes.
    Tickers below min_fraction of total are collapsed into a single "N others" node.
    """
    total = ticker_volumes.sum()
    if total == 0:
        return []

    ticker_volumes = ticker_volumes.sort_values(ascending=False)
    threshold = total * min_fraction

    visible = ticker_volumes[ticker_volumes >= threshold]
    collapsed = ticker_volumes[ticker_volumes < threshold]

    nodes = [
        {"name": ticker, "value": int(volume)}
        for ticker, volume in visible.items()
    ]

    if not collapsed.empty:
        nodes.append({
            "name": f"{len(collapsed)} others",
            "value": int(collapsed.sum()),
            "collapsed": True,
            "collapsed_tickers": [
                {"name": t, "value": int(v)}
                for t, v in collapsed.sort_values(ascending=False).items()
            ],
        })

    return nodes


def build_politician_node(politician: str, alpha_row: pd.Series, trades: pd.DataFrame, min_fraction: float) -> dict:
    """
    Builds a politician node with ticker children.
    Ticker volumes = sum of amount_mid for ALL trades (buy + sell) for that ticker.
    """
    ticker_volumes = trades.groupby("ticker")["amount_mid"].sum()
    ticker_nodes = build_ticker_nodes(ticker_volumes, min_fraction)

    node = {
        "name":           politician,
        "party_code":     alpha_row["party"][0] if alpha_row["party"] else "?",
        "weighted_alpha": None if np.isnan(alpha_row["weighted_alpha"]) else round(float(alpha_row["weighted_alpha"]), 4),
        "total_volume":   int(alpha_row["total_volume"]),
        "trade_count":    int(alpha_row["trade_count"]),
        "children":       ticker_nodes,
    }
    return node


def build_party_node(party: str, politicians_df: pd.DataFrame, trades: pd.DataFrame, min_fraction: float) -> dict:
    """
    Builds a party node with politician children, sorted by weighted_alpha descending.
    Politicians with NaN alpha are sorted to the end.
    """
    party_politicians = politicians_df[politicians_df["party"] == party].copy()

    # Sort: valid alpha descending first, NaN last
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
        node = build_politician_node(politician, alpha_row, politician_trades, min_fraction)
        children.append(node)

    return {
        "name":     party,
        "children": children,
    }


def build_hierarchy(alphas: pd.DataFrame, trades: pd.DataFrame, min_fraction: float = MIN_TICKER_FRACTION) -> dict:
    """
    Builds the full 3-layer hierarchy dict.
    Only includes parties that have at least one politician with trade data.
    """
    present_parties = alphas["party"].unique()
    ordered_parties = [p for p in PARTY_ORDER if p in present_parties]
    # Append any parties not in PARTY_ORDER (shouldn't happen, but be safe)
    ordered_parties += [p for p in present_parties if p not in ordered_parties]

    party_nodes = []
    for party in ordered_parties:
        node = build_party_node(party, alphas, trades, min_fraction)
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

    print(f"  {len(alphas)} politicians across parties: {alphas['party'].value_counts().to_dict()}")

    hierarchy = build_hierarchy(alphas, trades)

    total_politicians = sum(len(p["children"]) for p in hierarchy["children"])
    print(f"  Built hierarchy: {len(hierarchy['children'])} parties, {total_politicians} politicians")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(hierarchy, f, indent=2)
    print(f"  Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
