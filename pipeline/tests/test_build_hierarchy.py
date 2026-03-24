"""
Tests for build_hierarchy.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import numpy as np
import pandas as pd
import pytest
from build_hierarchy import (
    build_ticker_nodes,
    build_politician_node,
    build_party_node,
    build_hierarchy,
    PARTY_ORDER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_alphas(rows):
    return pd.DataFrame(rows)


def make_trades(rows):
    return pd.DataFrame(rows)


def make_alpha_row(politician="Alice", party="Democratic", weighted_alpha=0.10,
                   total_volume=500_000, trade_count=15):
    return pd.Series({
        "politician":     politician,
        "party":          party,
        "weighted_alpha": weighted_alpha,
        "total_volume":   total_volume,
        "trade_count":    trade_count,
    })


def make_politician_trades(politician="Alice", tickers=None):
    tickers = tickers or [("AAPL", 200_000), ("MSFT", 100_000)]
    rows = []
    for ticker, amount in tickers:
        rows.append({"politician": politician, "ticker": ticker, "amount_mid": amount, "type": "purchase"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# build_ticker_nodes
# ---------------------------------------------------------------------------

class TestBuildTickerNodes:
    def test_all_visible_when_above_threshold(self):
        volumes = pd.Series({"AAPL": 300_000, "MSFT": 200_000})
        nodes = build_ticker_nodes(volumes, min_fraction=0.03)
        names = [n["name"] for n in nodes]
        assert "AAPL" in names
        assert "MSFT" in names
        assert not any(n.get("collapsed") for n in nodes)

    def test_small_tickers_collapsed(self):
        # TINY is 1% of total → below 3% threshold
        volumes = pd.Series({"AAPL": 490_000, "TINY": 5_000, "SMALL": 5_000})
        nodes = build_ticker_nodes(volumes, min_fraction=0.03)
        names = [n["name"] for n in nodes]
        assert "AAPL" in names
        assert "TINY" not in names
        assert "SMALL" not in names
        others = next(n for n in nodes if n.get("collapsed"))
        assert others["name"] == "2 others"
        assert others["value"] == 10_000

    def test_collapsed_tickers_sorted_by_volume_desc(self):
        volumes = pd.Series({"AAPL": 900_000, "BB": 5_000, "CC": 2_000})
        nodes = build_ticker_nodes(volumes, min_fraction=0.03)
        others = next(n for n in nodes if n.get("collapsed"))
        assert others["collapsed_tickers"][0]["name"] == "BB"
        assert others["collapsed_tickers"][1]["name"] == "CC"

    def test_no_others_node_when_nothing_collapsed(self):
        volumes = pd.Series({"AAPL": 500_000, "MSFT": 500_000})
        nodes = build_ticker_nodes(volumes, min_fraction=0.03)
        assert not any(n.get("collapsed") for n in nodes)

    def test_visible_tickers_sorted_by_volume_desc(self):
        volumes = pd.Series({"BB": 100_000, "AAPL": 400_000})
        nodes = build_ticker_nodes(volumes, min_fraction=0.0)
        assert nodes[0]["name"] == "AAPL"
        assert nodes[1]["name"] == "BB"

    def test_empty_series_returns_empty_list(self):
        assert build_ticker_nodes(pd.Series(dtype=float), min_fraction=0.03) == []

    def test_zero_total_returns_empty_list(self):
        volumes = pd.Series({"AAPL": 0})
        assert build_ticker_nodes(volumes, min_fraction=0.03) == []


# ---------------------------------------------------------------------------
# build_politician_node
# ---------------------------------------------------------------------------

class TestBuildPoliticianNode:
    def test_required_fields_present(self):
        row = make_alpha_row()
        trades = make_politician_trades()
        node = build_politician_node("Alice", row, trades, min_fraction=0.0, current_legislators=set())
        for field in ["name", "party_code", "weighted_alpha", "total_volume", "trade_count", "children"]:
            assert field in node

    def test_name_set_correctly(self):
        node = build_politician_node("Alice", make_alpha_row(), make_politician_trades(), min_fraction=0.0, current_legislators=set())
        assert node["name"] == "Alice"

    def test_weighted_alpha_rounded(self):
        row = make_alpha_row(weighted_alpha=0.123456789)
        node = build_politician_node("Alice", row, make_politician_trades(), min_fraction=0.0, current_legislators=set())
        assert node["weighted_alpha"] == pytest.approx(0.1235, abs=1e-4)

    def test_nan_alpha_stored_as_none(self):
        row = make_alpha_row(weighted_alpha=np.nan)
        node = build_politician_node("Alice", row, make_politician_trades(), min_fraction=0.0, current_legislators=set())
        assert node["weighted_alpha"] is None

    def test_ticker_volumes_summed_across_all_trade_types(self):
        trades = pd.DataFrame([
            {"politician": "Alice", "ticker": "AAPL", "amount_mid": 100_000, "type": "purchase"},
            {"politician": "Alice", "ticker": "AAPL", "amount_mid":  50_000, "type": "sale"},
        ])
        node = build_politician_node("Alice", make_alpha_row(), trades, min_fraction=0.0, current_legislators=set())
        aapl = next(n for n in node["children"] if n["name"] == "AAPL")
        assert aapl["value"] == 150_000

    def test_json_serializable(self):
        node = build_politician_node("Alice", make_alpha_row(), make_politician_trades(), min_fraction=0.0, current_legislators=set())
        json.dumps(node)  # should not raise


# ---------------------------------------------------------------------------
# build_party_node
# ---------------------------------------------------------------------------

def make_alphas_df():
    return pd.DataFrame([
        {"politician": "Alice", "party": "Democratic", "weighted_alpha": 0.20, "total_volume": 500_000, "trade_count": 20},
        {"politician": "Bob",   "party": "Democratic", "weighted_alpha": 0.05, "total_volume": 300_000, "trade_count": 12},
        {"politician": "Carol", "party": "Democratic", "weighted_alpha": np.nan, "total_volume": 200_000, "trade_count": 10},
    ])


def make_multi_politician_trades():
    rows = []
    for politician in ["Alice", "Bob", "Carol"]:
        rows.append({"politician": politician, "ticker": "AAPL", "amount_mid": 100_000, "type": "purchase"})
    return pd.DataFrame(rows)


class TestBuildPartyNode:
    def test_party_name_set(self):
        node = build_party_node("Democratic", make_alphas_df(), make_multi_politician_trades(), 0.0, set())
        assert node["name"] == "Democratic"

    def test_politicians_sorted_by_alpha_descending(self):
        node = build_party_node("Democratic", make_alphas_df(), make_multi_politician_trades(), 0.0, set())
        names = [c["name"] for c in node["children"]]
        assert names[0] == "Alice"   # alpha=0.20
        assert names[1] == "Bob"     # alpha=0.05

    def test_nan_alpha_politicians_sorted_last(self):
        node = build_party_node("Democratic", make_alphas_df(), make_multi_politician_trades(), 0.0, set())
        names = [c["name"] for c in node["children"]]
        assert names[-1] == "Carol"  # alpha=NaN

    def test_only_includes_politicians_with_trades(self):
        # Dave is in alphas but has no trades
        alphas = make_alphas_df()
        alphas = pd.concat([alphas, pd.DataFrame([{
            "politician": "Dave", "party": "Democratic",
            "weighted_alpha": 0.30, "total_volume": 100_000, "trade_count": 5
        }])], ignore_index=True)
        node = build_party_node("Democratic", alphas, make_multi_politician_trades(), 0.0, set())
        names = [c["name"] for c in node["children"]]
        assert "Dave" not in names


# ---------------------------------------------------------------------------
# build_hierarchy
# ---------------------------------------------------------------------------

def make_full_alphas():
    return pd.DataFrame([
        {"politician": "Alice", "party": "Democratic",  "weighted_alpha": 0.15, "total_volume": 500_000, "trade_count": 20},
        {"politician": "Bob",   "party": "Republican",  "weighted_alpha": 0.08, "total_volume": 300_000, "trade_count": 12},
    ])


def make_full_trades():
    rows = []
    for politician in ["Alice", "Bob"]:
        rows.append({"politician": politician, "ticker": "AAPL", "amount_mid": 100_000, "type": "purchase"})
    return pd.DataFrame(rows)


class TestBuildHierarchy:
    def test_root_name_is_congress(self):
        h = build_hierarchy(make_full_alphas(), make_full_trades(), set())
        assert h["name"] == "Congress"

    def test_parties_in_canonical_order(self):
        h = build_hierarchy(make_full_alphas(), make_full_trades(), set())
        party_names = [p["name"] for p in h["children"]]
        dem_idx = party_names.index("Democratic")
        rep_idx = party_names.index("Republican")
        assert dem_idx < rep_idx

    def test_empty_parties_excluded(self):
        # Only Democratic and Republican present — Independent/Other should not appear
        h = build_hierarchy(make_full_alphas(), make_full_trades(), set())
        party_names = [p["name"] for p in h["children"]]
        assert "Independent" not in party_names
        assert "Other" not in party_names

    def test_full_structure_is_json_serializable(self):
        h = build_hierarchy(make_full_alphas(), make_full_trades(), set())
        json.dumps(h)  # should not raise

    def test_leaf_nodes_have_value_field(self):
        h = build_hierarchy(make_full_alphas(), make_full_trades(), set())
        for party in h["children"]:
            for politician in party["children"]:
                for ticker in politician["children"]:
                    assert "value" in ticker

    def test_is_current_tagged_correctly(self):
        current = {"alice"}  # lowercase match
        h = build_hierarchy(make_full_alphas(), make_full_trades(), current)
        politicians = {p["name"]: p for party in h["children"] for p in party["children"]}
        assert politicians["Alice"]["is_current"] is True
        assert politicians["Bob"]["is_current"] is False
