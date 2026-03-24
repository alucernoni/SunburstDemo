"""
Tests for fetch_trades.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from fetch_trades import parse_amount, clean, filter_active_traders, load_raw, find_raw_csv


# ---------------------------------------------------------------------------
# parse_amount
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_known_ranges_return_correct_midpoints(self):
        assert parse_amount("$1,001 - $15,000") == 8_000
        assert parse_amount("$15,001 - $50,000") == 32_500
        assert parse_amount("$50,001 - $100,000") == 75_000
        assert parse_amount("$100,001 - $250,000") == 175_000
        assert parse_amount("$250,001 - $500,000") == 375_000
        assert parse_amount("$500,001 - $1,000,000") == 750_000
        assert parse_amount("$1,000,001 - $5,000,000") == 2_500_000

    def test_open_ended_cap_uses_agreed_midpoint(self):
        assert parse_amount("$1,000,001 - $5,000,000") == 2_500_000

    def test_unknown_range_returns_none(self):
        assert parse_amount("$999 - $1,000") is None
        assert parse_amount("unknown") is None
        assert parse_amount("") is None

    def test_non_string_returns_none(self):
        assert parse_amount(None) is None
        assert parse_amount(12345) is None

    def test_leading_trailing_whitespace_handled(self):
        assert parse_amount("  $1,001 - $15,000  ") == 8_000


# ---------------------------------------------------------------------------
# find_raw_csv / load_raw
# ---------------------------------------------------------------------------

class TestFindRawCsv:
    def test_finds_csv_in_directory(self, tmp_path):
        csv = tmp_path / "trades.csv"
        csv.write_text("col\nval")
        assert find_raw_csv(str(tmp_path)) == str(csv)

    def test_raises_if_no_csv(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            find_raw_csv(str(tmp_path))


class TestLoadRaw:
    def test_columns_renamed_to_canonical_names(self, tmp_path):
        csv = tmp_path / "trades.csv"
        csv.write_text(
            "Name,Party,Chamber,Ticker,Transaction,Trade_Size_USD,Traded\n"
            "Nancy Pelosi,D,House,AAPL,Purchase,$1\\,001 - $15\\,000,2023-01-15\n"
        )
        df = load_raw(str(tmp_path))
        for col in ["politician", "party", "chamber", "ticker", "type", "amount_str", "date"]:
            assert col in df.columns

    def test_raises_if_no_csv(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_raw(str(tmp_path))


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------

def make_raw_df(overrides=None):
    base = {
        "politician": ["Alice Smith", "Bob Jones"],
        "party":      ["D", "R"],
        "chamber":    ["House", "Senate"],
        "ticker":     ["AAPL", "MSFT"],
        "type":       ["purchase", "sale"],
        "date":       ["2023-01-15", "2023-03-20"],
        "amount_str": ["$15,001 - $50,000", "$50,001 - $100,000"],
    }
    if overrides:
        base.update(overrides)
    return pd.DataFrame(base)


class TestClean:
    def test_valid_rows_are_kept(self):
        assert len(clean(make_raw_df())) == 2

    def test_amount_mid_column_added(self):
        df = clean(make_raw_df())
        assert "amount_mid" in df.columns
        assert df.iloc[0]["amount_mid"] == 32_500
        assert df.iloc[1]["amount_mid"] == 75_000

    def test_rows_with_unknown_amount_dropped(self):
        df = clean(make_raw_df({"amount_str": ["bad range", "$15,001 - $50,000"]}))
        assert len(df) == 1
        assert df.iloc[0]["politician"] == "Bob Jones"

    def test_rows_with_empty_ticker_dropped(self):
        assert len(clean(make_raw_df({"ticker": ["", "MSFT"]}))) == 1

    def test_rows_with_placeholder_ticker_dropped(self):
        for bad in ["--", "N/A"]:
            assert len(clean(make_raw_df({"ticker": [bad, "MSFT"]}))) == 1

    def test_rows_with_bad_date_dropped(self):
        assert len(clean(make_raw_df({"date": ["not-a-date", "2023-03-20"]}))) == 1

    def test_date_parsed_to_datetime(self):
        df = clean(make_raw_df())
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_kaggle_date_format_parsed(self):
        df = clean(make_raw_df({"date": ["Monday, March 11, 2024", "Thursday, February 29, 2024"]}))
        assert len(df) == 2
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_type_normalized_to_lowercase(self):
        df = clean(make_raw_df({"type": ["Purchase", "SALE"]}))
        assert list(df["type"]) == ["purchase", "sale"]

    def test_honorifics_stripped_from_politician_names(self):
        raw = make_raw_df({"politician": ["Mark Dr Green", "Dr. Jane Smith"]})
        df = clean(raw)
        assert list(df["politician"]) == ["Mark Green", "Jane Smith"]

    def test_duplicate_names_after_honorific_strip_merge_correctly(self):
        # "Mark Dr Green" and "Mark Green" should become the same politician
        rows = {
            "politician": ["Mark Dr Green"] * 10 + ["Mark Green"] * 5,
            "party":      ["R"] * 15,
            "chamber":    ["House"] * 15,
            "ticker":     ["AAPL"] * 15,
            "type":       ["purchase"] * 15,
            "date":       ["2023-01-15"] * 15,
            "amount_str": ["$15,001 - $50,000"] * 15,
        }
        df = clean(pd.DataFrame(rows))
        assert df["politician"].nunique() == 1
        assert df["politician"].iloc[0] == "Mark Green"


# ---------------------------------------------------------------------------
# filter_active_traders
# ---------------------------------------------------------------------------

def make_trades_df(purchase_counts: dict) -> pd.DataFrame:
    rows = []
    for politician, n_purchases in purchase_counts.items():
        for _ in range(n_purchases):
            rows.append({"politician": politician, "type": "purchase", "amount_mid": 10_000})
        rows.append({"politician": politician, "type": "sale", "amount_mid": 10_000})
    return pd.DataFrame(rows)


class TestFilterActiveTraders:
    def test_politicians_below_threshold_excluded(self):
        df = make_trades_df({"Active": 10, "Inactive": 9})
        assert "Inactive" not in filter_active_traders(df)["politician"].values

    def test_politicians_at_threshold_included(self):
        df = make_trades_df({"ExactlyTen": 10})
        assert "ExactlyTen" in filter_active_traders(df)["politician"].values

    def test_sales_do_not_count_toward_threshold(self):
        rows = [{"politician": "SalesHeavy", "type": "sale",     "amount_mid": 10_000}] * 20
        rows += [{"politician": "SalesHeavy", "type": "purchase", "amount_mid": 10_000}] * 9
        assert "SalesHeavy" not in filter_active_traders(pd.DataFrame(rows))["politician"].values

    def test_all_rows_for_active_trader_preserved(self):
        df = make_trades_df({"Active": 10})
        result = filter_active_traders(df)
        assert len(result[result["politician"] == "Active"]) == 11  # 10 purchases + 1 sale

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["politician", "type", "amount_mid"])
        assert len(filter_active_traders(df)) == 0
