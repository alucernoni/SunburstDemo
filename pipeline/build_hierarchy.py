"""
build_hierarchy.py

Assembles hierarchy.json for the D3 sunburst from trades.csv + alphas.csv.

Structure:
  Congress (root)
    └── Party             (inner ring)
          └── Politician  (middle ring) — sized by total volume, colored by weighted_alpha
                └── Ticker              (outer ring) — sized by volume for that ticker
                └── "N others"          (collapsed if beyond max visible tickers for this politician)

Outputs: public/hierarchy.json
"""

import json
import math
import os
import numpy as np
import pandas as pd

TRADES_PATH       = "data/trades.csv"
ALPHAS_PATH       = "data/alphas.csv"
OUTPUT_PATH       = "public/hierarchy.json"
LEGISLATORS_PATH  = "pipeline/data/raw/legislators-current.csv"

# ── Ticker visibility sizing ────────────────────────────────────────────────
# max_visible per politician = floor(eff_arc / MIN_TICKER_ARC_RAD)
# where eff_arc is the politician's arc after enforceMinPoliticianArcs
# (computed here to stay in sync with the frontend rendering).
#
# Must stay in sync with:
#   App.tsx        MAX_SIZE = 800, POLITICIAN_MAX_VISIBLE = 24, POLITICIAN_COLLAPSE_FRACTION = 0.10
#   Sunburst.tsx   MIN_ARC_PX[2] = 20, RING2_MID_FRACTION = 5/8, LABEL_FLOOR_ALPHA = 0.5
#                  MIN_ARC_PX[3] = 18, RING3_MID_FRACTION = 7/8, TICKER_FLOOR_ALPHA = 0.8
ASSUMED_CHART_PX  = 800         # MAX_SIZE in App.tsx
_RADIUS           = ASSUMED_CHART_PX / 2

# Ring-2 geometry (politician ring) — for computing effective politician arcs
_RING2_MID_PX     = _RADIUS * (5 / 8)   # 250 px
MIN_POL_ARC_PX    = 20                   # MIN_ARC_PX[2] in Sunburst.tsx
MIN_POL_ARC_RAD   = MIN_POL_ARC_PX / _RING2_MID_PX    # ≈ 0.080 rad per politician
POL_FLOOR_ALPHA   = 0.5                  # LABEL_FLOOR_ALPHA in Sunburst.tsx

# Ring-3 geometry (ticker ring)
_RING3_MID_PX     = _RADIUS * (7 / 8)   # 350 px
MIN_TICKER_ARC_PX = 18                   # MIN_ARC_PX[3] in Sunburst.tsx
MIN_TICKER_ARC_RAD = MIN_TICKER_ARC_PX / _RING3_MID_PX  # ≈ 0.0514 rad per ticker

# Frontend collapse constants (approximate collapseSmallPoliticians in App.tsx)
POLITICIAN_MAX_VISIBLE       = 24    # POLITICIAN_MAX_VISIBLE in App.tsx
POLITICIAN_COLLAPSE_FRACTION = 0.10  # POLITICIAN_COLLAPSE_FRACTION in App.tsx

# Minimum visible tickers — safety floor for very small politicians
MIN_VISIBLE_TICKERS = 5

# Canonical party display order in the sunburst (clockwise)
PARTY_ORDER = ["Democratic", "Republican", "Independent", "Other"]


def compute_effective_pol_arcs(alphas: pd.DataFrame, total_congress_volume: float) -> dict:
    """
    Approximates the effective arc each politician receives in the chart, mirroring
    the frontend's enforceMinPoliticianArcs + approximate collapseSmallPoliticians.

    Returns {politician_name: arc_radians}.
    Politicians that would be collapsed into "N others" in the frontend get their
    raw proportional arc (they won't show individual tickers anyway).
    """
    TWO_PI = 2 * math.pi
    eff_arcs = {}

    for party, group in alphas.groupby("party"):
        party_arc = group["total_volume"].sum() / total_congress_volume * TWO_PI

        # Approximate collapseSmallPoliticians: keep top POLITICIAN_MAX_VISIBLE by volume.
        sorted_pols = group.sort_values("total_volume", ascending=False)
        visible_pols  = sorted_pols.head(POLITICIAN_MAX_VISIBLE)
        collapsed_pols = sorted_pols.iloc[POLITICIAN_MAX_VISIBLE:]

        visible_vol = visible_pols["total_volume"].sum()
        n = len(visible_pols)

        # Replicate enforceMinPoliticianArcs Case-1 / Case-2 logic
        if n > 0 and n * MIN_POL_ARC_RAD <= party_arc:
            floor_arc = MIN_POL_ARC_RAD
        elif n > 0:
            floor_arc = (party_arc / n) * POL_FLOOR_ALPHA
        else:
            floor_arc = 0.0

        remaining = max(0.0, party_arc - n * floor_arc)

        for _, row in visible_pols.iterrows():
            fraction = row["total_volume"] / visible_vol if visible_vol > 0 else 1.0 / n
            eff_arcs[row["politician"]] = floor_arc + fraction * remaining

        # Collapsed politicians: fall back to raw arc (used only as safety floor input)
        for _, row in collapsed_pols.iterrows():
            raw_arc = row["total_volume"] / total_congress_volume * TWO_PI
            eff_arcs[row["politician"]] = raw_arc

    return eff_arcs


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


def build_ticker_nodes(ticker_volumes: pd.Series, max_visible: int) -> list:
    """
    Given a Series of {ticker: volume}, returns a list of leaf nodes.
    At most max_visible tickers are shown; the rest are collapsed into "N others".
    max_visible is computed from the politician's effective arc in the chart.
    """
    total = ticker_volumes.sum()
    if total == 0:
        return []

    ticker_volumes = ticker_volumes.sort_values(ascending=False)

    visible  = ticker_volumes.head(max_visible)
    collapsed = ticker_volumes.iloc[max_visible:]

    nodes = [
        {"name": ticker, "value": int(volume)}
        for ticker, volume in visible.items()
    ]

    if len(collapsed) == 1:
        # Never show "1 other" — just display the ticker directly
        nodes.append({"name": collapsed.index[0], "value": int(collapsed.iloc[0])})
    elif not collapsed.empty:
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


def build_politician_node(politician: str, alpha_row: pd.Series, trades: pd.DataFrame,
                          eff_arc: float, current_legislators: set) -> dict:
    """
    Builds a politician node with ticker children.
    Ticker volumes = sum of amount_mid for ALL trades (buy + sell) for that ticker.
    max_visible = floor(eff_arc / MIN_TICKER_ARC_RAD) — matches labeled capacity in chart.
    """
    ticker_volumes = trades.groupby("ticker")["amount_mid"].sum()

    max_visible = max(math.floor(eff_arc / MIN_TICKER_ARC_RAD), MIN_VISIBLE_TICKERS)
    ticker_nodes = build_ticker_nodes(ticker_volumes, max_visible)

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
                     eff_arcs: dict, current_legislators: set) -> dict:
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
        eff_arc = eff_arcs.get(politician, 0.0)
        node = build_politician_node(politician, alpha_row, politician_trades, eff_arc, current_legislators)
        children.append(node)

    return {
        "name":     party,
        "children": children,
    }


def build_hierarchy(alphas: pd.DataFrame, trades: pd.DataFrame,
                    current_legislators: set) -> dict:
    """
    Builds the full 3-layer hierarchy dict.
    Only includes parties that have at least one politician with trade data.
    """
    total_congress_volume = float(alphas["total_volume"].sum())
    eff_arcs = compute_effective_pol_arcs(alphas, total_congress_volume)

    present_parties = alphas["party"].unique()
    ordered_parties = [p for p in PARTY_ORDER if p in present_parties]
    ordered_parties += [p for p in present_parties if p not in ordered_parties]

    party_nodes = []
    for party in ordered_parties:
        node = build_party_node(party, alphas, trades, eff_arcs, current_legislators)
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

    print(f"Loading current legislators from {LEGISLATORS_PATH}...")
    current_legislators = load_current_legislators(LEGISLATORS_PATH)

    print(f"  {len(alphas)} politicians across parties: {alphas['party'].value_counts().to_dict()}")

    current_count = sum(1 for n in alphas["politician"] if n.strip().lower() in current_legislators)
    print(f"  Currently serving matched: {current_count}/{len(alphas)}")

    hierarchy = build_hierarchy(alphas, trades, current_legislators)

    total_politicians = sum(len(p["children"]) for p in hierarchy["children"])
    print(f"  Built hierarchy: {len(hierarchy['children'])} parties, {total_politicians} politicians")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(hierarchy, f, indent=2)
    print(f"  Saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
