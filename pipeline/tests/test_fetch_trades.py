"""
Tests for fetch_trades.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from fetch_trades import parse_amount, clean, filter_active_traders, fetch_house, fetch_senate


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
        # Agreed: $1M+ open-ended → $2,500,000
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
# clean
# ---------------------------------------------------------------------------

def make_raw_df(overrides=None):
    """Helper: returns a minimal valid raw DataFrame."""
    base = {
        "politician": ["Alice Smith", "Bob Jones"],
        "party":      ["Democrat", "Republican"],
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
        df = clean(make_raw_df())
        assert len(df) == 2

    def test_amount_mid_column_added(self):
        df = clean(make_raw_df())
        assert "amount_mid" in df.columns
        assert df.iloc[0]["amount_mid"] == 32_500
        assert df.iloc[1]["amount_mid"] == 75_000

    def test_rows_with_unknown_amount_dropped(self):
        raw = make_raw_df({"amount_str": ["bad range", "$15,001 - $50,000"]})
        df = clean(raw)
        assert len(df) == 1
        assert df.iloc[0]["politician"] == "Bob Jones"

    def test_rows_with_empty_ticker_dropped(self):
        raw = make_raw_df({"ticker": ["", "MSFT"]})
        df = clean(raw)
        assert len(df) == 1

    def test_rows_with_placeholder_ticker_dropped(self):
        for bad_ticker in ["--", "N/A"]:
            raw = make_raw_df({"ticker": [bad_ticker, "MSFT"]})
            df = clean(raw)
            assert len(df) == 1, f"Expected {bad_ticker} to be dropped"

    def test_rows_with_bad_date_dropped(self):
        raw = make_raw_df({"date": ["not-a-date", "2023-03-20"]})
        df = clean(raw)
        assert len(df) == 1

    def test_date_parsed_to_datetime(self):
        df = clean(make_raw_df())
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_type_normalized_to_lowercase(self):
        raw = make_raw_df({"type": ["Purchase", "SALE"]})
        df = clean(raw)
        assert list(df["type"]) == ["purchase", "sale"]


# ---------------------------------------------------------------------------
# filter_active_traders
# ---------------------------------------------------------------------------

def make_trades_df(purchase_counts: dict) -> pd.DataFrame:
    """
    Helper: builds a DataFrame with the given number of purchases per politician.
    Each politician also gets 1 sale row to confirm sales don't count toward threshold.
    """
    rows = []
    for politician, n_purchases in purchase_counts.items():
        for _ in range(n_purchases):
            rows.append({"politician": politician, "type": "purchase", "amount_mid": 10_000})
        rows.append({"politician": politician, "type": "sale", "amount_mid": 10_000})
    return pd.DataFrame(rows)


class TestFilterActiveTraders:
    def test_politicians_below_threshold_excluded(self):
        df = make_trades_df({"ActiveTrader": 10, "InactiveTrader": 9})
        result = filter_active_traders(df)
        assert "InactiveTrader" not in result["politician"].values

    def test_politicians_at_threshold_included(self):
        df = make_trades_df({"ExactlyTen": 10})
        result = filter_active_traders(df)
        assert "ExactlyTen" in result["politician"].values

    def test_sales_do_not_count_toward_threshold(self):
        # 9 purchases + many sales → should still be excluded
        rows = [{"politician": "SalesHeavy", "type": "sale", "amount_mid": 10_000}] * 20
        rows += [{"politician": "SalesHeavy", "type": "purchase", "amount_mid": 10_000}] * 9
        df = pd.DataFrame(rows)
        result = filter_active_traders(df)
        assert "SalesHeavy" not in result["politician"].values

    def test_all_rows_for_active_trader_preserved(self):
        # Active trader's sales should be in output (volume uses all trades)
        df = make_trades_df({"Active": 10})
        result = filter_active_traders(df)
        assert len(result[result["politician"] == "Active"]) == 11  # 10 purchases + 1 sale

    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame(columns=["politician", "type", "amount_mid"])
        result = filter_active_traders(df)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# fetch_house / fetch_senate (network mocked)
# ---------------------------------------------------------------------------

MOCK_HOUSE_RESPONSE = [
    {
        "representative": "Nancy Pelosi",
        "party": "Democrat",
        "ticker": "aapl",
        "type": "Purchase",
        "transaction_date": "2023-06-01",
        "amount": "$1,001 - $15,000",
    }
]

MOCK_SENATE_RESPONSE = [
    {
        "senator": "John Doe",
        "party": "Republican",
        "ticker": "msft",
        "type": "Sale",
        "transaction_date": "2023-07-15",
        "amount": "$50,001 - $100,000",
    }
]


class TestFetchHouse:
    @patch("fetch_trades.requests.get")
    def test_returns_dataframe_with_expected_columns(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_HOUSE_RESPONSE)
        df = fetch_house()
        for col in ["politician", "party", "chamber", "ticker", "type", "date", "amount_str"]:
            assert col in df.columns

    @patch("fetch_trades.requests.get")
    def test_ticker_uppercased(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_HOUSE_RESPONSE)
        df = fetch_house()
        assert df.iloc[0]["ticker"] == "AAPL"

    @patch("fetch_trades.requests.get")
    def test_chamber_set_to_house(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_HOUSE_RESPONSE)
        df = fetch_house()
        assert df.iloc[0]["chamber"] == "House"


class TestFetchSenate:
    @patch("fetch_trades.requests.get")
    def test_returns_dataframe_with_expected_columns(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_SENATE_RESPONSE)
        df = fetch_senate()
        for col in ["politician", "party", "chamber", "ticker", "type", "date", "amount_str"]:
            assert col in df.columns

    @patch("fetch_trades.requests.get")
    def test_senator_field_mapped_to_politician(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_SENATE_RESPONSE)
        df = fetch_senate()
        assert df.iloc[0]["politician"] == "John Doe"

    @patch("fetch_trades.requests.get")
    def test_chamber_set_to_senate(self, mock_get):
        mock_get.return_value = MagicMock(json=lambda: MOCK_SENATE_RESPONSE)
        df = fetch_senate()
        assert df.iloc[0]["chamber"] == "Senate"
