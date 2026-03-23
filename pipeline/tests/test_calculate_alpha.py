"""
Tests for calculate_alpha.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch
from calculate_alpha import (
    normalize_party,
    compute_return,
    compute_alpha_for_purchase,
    compute_alphas,
    aggregate_by_politician,
    ALPHA_WINDOW_DAYS,
)


# ---------------------------------------------------------------------------
# normalize_party
# ---------------------------------------------------------------------------

class TestNormalizeParty:
    def test_democrat_variants(self):
        for raw in ["Democrat", "democratic", "D", "d"]:
            assert normalize_party(raw) == "Democratic", f"Failed for: {raw}"

    def test_republican_variants(self):
        for raw in ["Republican", "republican", "R", "r"]:
            assert normalize_party(raw) == "Republican", f"Failed for: {raw}"

    def test_independent_variants(self):
        for raw in ["Independent", "independent", "I", "i"]:
            assert normalize_party(raw) == "Independent", f"Failed for: {raw}"

    def test_unknown_returns_other(self):
        assert normalize_party("Green") == "Other"
        assert normalize_party("") == "Other"

    def test_non_string_returns_other(self):
        assert normalize_party(None) == "Other"
        assert normalize_party(42) == "Other"


# ---------------------------------------------------------------------------
# compute_return
# ---------------------------------------------------------------------------

class TestComputeReturn:
    def test_basic_gain(self):
        assert compute_return(100.0, 110.0) == pytest.approx(0.10)

    def test_basic_loss(self):
        assert compute_return(100.0, 90.0) == pytest.approx(-0.10)

    def test_no_change(self):
        assert compute_return(100.0, 100.0) == pytest.approx(0.0)

    def test_zero_start_price_returns_none(self):
        assert compute_return(0.0, 100.0) is None

    def test_none_start_returns_none(self):
        assert compute_return(None, 100.0) is None

    def test_none_end_returns_none(self):
        assert compute_return(100.0, None) is None


# ---------------------------------------------------------------------------
# compute_alpha_for_purchase
# ---------------------------------------------------------------------------

def make_purchase_row(ticker="AAPL", date="2023-01-15"):
    return pd.Series({
        "ticker":     ticker,
        "date":       pd.Timestamp(date),
        "type":       "purchase",
        "amount_mid": 50_000,
    })


class TestComputeAlphaForPurchase:
    @patch("calculate_alpha.get_price_on_or_after")
    def test_alpha_computed_correctly(self, mock_price):
        # stock: +20%, SPY: +10% → alpha = 0.10
        def side_effect(ticker, date, prices_dir):
            if ticker == "SPY":
                return 400.0 if date == pd.Timestamp("2023-01-15") else 440.0
            return 150.0 if date == pd.Timestamp("2023-01-15") else 180.0

        mock_price.side_effect = side_effect
        row = make_purchase_row()
        alpha = compute_alpha_for_purchase(row, pd.Timestamp("2024-06-01"), "data/prices")
        assert alpha == pytest.approx(0.10, abs=1e-6)

    @patch("calculate_alpha.get_price_on_or_after")
    def test_missing_stock_price_returns_none(self, mock_price):
        mock_price.return_value = None
        row = make_purchase_row()
        alpha = compute_alpha_for_purchase(row, pd.Timestamp("2024-06-01"), "data/prices")
        assert alpha is None

    @patch("calculate_alpha.get_price_on_or_after")
    def test_recent_purchase_uses_today_as_end(self, mock_price):
        """Purchases < 1 year ago should use today, not purchase_date + 365."""
        today = pd.Timestamp("2024-06-01")
        purchase_date = today - pd.Timedelta(days=30)  # 30 days ago

        captured_end_dates = []
        def side_effect(ticker, date, prices_dir):
            captured_end_dates.append(date)
            return 150.0

        mock_price.side_effect = side_effect
        row = make_purchase_row(date=str(purchase_date.date()))
        compute_alpha_for_purchase(row, today, "data/prices")

        end_dates = [d for d in captured_end_dates if d != purchase_date]
        assert all(d <= today for d in end_dates)

    @patch("calculate_alpha.get_price_on_or_after")
    def test_old_purchase_uses_1_year_window(self, mock_price):
        """Purchases > 1 year ago should use purchase_date + 365 as end."""
        today = pd.Timestamp("2024-06-01")
        purchase_date = pd.Timestamp("2022-01-15")
        expected_end = purchase_date + pd.Timedelta(days=ALPHA_WINDOW_DAYS)

        captured_end_dates = []
        def side_effect(ticker, date, prices_dir):
            captured_end_dates.append(date)
            return 150.0

        mock_price.side_effect = side_effect
        row = make_purchase_row(date="2022-01-15")
        compute_alpha_for_purchase(row, today, "data/prices")

        end_dates = [d for d in captured_end_dates if d != purchase_date]
        assert any(abs((d - expected_end).days) <= 1 for d in end_dates)


# ---------------------------------------------------------------------------
# compute_alphas
# ---------------------------------------------------------------------------

def make_trades_df():
    return pd.DataFrame([
        {"politician": "Alice", "ticker": "AAPL", "type": "purchase", "date": pd.Timestamp("2022-06-01"), "amount_mid": 50_000, "party": "Democrat"},
        {"politician": "Alice", "ticker": "MSFT", "type": "sale",     "date": pd.Timestamp("2022-09-01"), "amount_mid": 30_000, "party": "Democrat"},
        {"politician": "Bob",   "ticker": "TSLA", "type": "purchase", "date": pd.Timestamp("2022-03-01"), "amount_mid": 75_000, "party": "Republican"},
    ])


class TestComputeAlphas:
    @patch("calculate_alpha.compute_alpha_for_purchase")
    def test_alpha_added_to_purchase_rows(self, mock_alpha):
        mock_alpha.return_value = 0.05
        df = make_trades_df()
        result = compute_alphas(df, pd.Timestamp("2024-01-01"), "data/prices")
        purchase_alphas = result[result["type"] == "purchase"]["alpha"]
        assert (purchase_alphas == 0.05).all()

    @patch("calculate_alpha.compute_alpha_for_purchase")
    def test_sale_rows_get_nan_alpha(self, mock_alpha):
        mock_alpha.return_value = 0.05
        df = make_trades_df()
        result = compute_alphas(df, pd.Timestamp("2024-01-01"), "data/prices")
        sale_alphas = result[result["type"] == "sale"]["alpha"]
        assert sale_alphas.isna().all()

    @patch("calculate_alpha.compute_alpha_for_purchase")
    def test_none_alpha_stored_as_nan(self, mock_alpha):
        mock_alpha.return_value = None
        df = make_trades_df()
        result = compute_alphas(df, pd.Timestamp("2024-01-01"), "data/prices")
        assert result["alpha"].isna().all()


# ---------------------------------------------------------------------------
# aggregate_by_politician
# ---------------------------------------------------------------------------

def make_trades_with_alpha():
    return pd.DataFrame([
        # Alice: 2 purchases with known alpha, 1 sale
        {"politician": "Alice", "party": "Democrat",    "type": "purchase", "amount_mid": 100_000, "alpha": 0.20},
        {"politician": "Alice", "party": "Democrat",    "type": "purchase", "amount_mid": 100_000, "alpha": 0.10},
        {"politician": "Alice", "party": "Democrat",    "type": "sale",     "amount_mid":  50_000, "alpha": np.nan},
        # Bob: 1 purchase with known alpha
        {"politician": "Bob",   "party": "Republican",  "type": "purchase", "amount_mid":  75_000, "alpha": -0.05},
        # Carol: purchases but all alpha is NaN (delisted stock etc.)
        {"politician": "Carol", "party": "Democrat",    "type": "purchase", "amount_mid":  40_000, "alpha": np.nan},
    ])


class TestAggregateByPolitician:
    def test_weighted_alpha_computed_correctly(self):
        df = make_trades_with_alpha()
        result = aggregate_by_politician(df)
        alice = result[result["politician"] == "Alice"].iloc[0]
        # equal weights → simple average of 0.20 and 0.10 = 0.15
        assert alice["weighted_alpha"] == pytest.approx(0.15)

    def test_total_volume_includes_all_trades(self):
        df = make_trades_with_alpha()
        result = aggregate_by_politician(df)
        alice = result[result["politician"] == "Alice"].iloc[0]
        assert alice["total_volume"] == 250_000  # 100k + 100k + 50k

    def test_trade_count_includes_all_trades(self):
        df = make_trades_with_alpha()
        result = aggregate_by_politician(df)
        alice = result[result["politician"] == "Alice"].iloc[0]
        assert alice["trade_count"] == 3

    def test_nan_alpha_when_no_valid_purchases(self):
        df = make_trades_with_alpha()
        result = aggregate_by_politician(df)
        carol = result[result["politician"] == "Carol"].iloc[0]
        assert np.isnan(carol["weighted_alpha"])

    def test_party_normalized(self):
        df = make_trades_with_alpha()
        result = aggregate_by_politician(df)
        assert set(result["party"]) <= {"Democratic", "Republican", "Independent", "Other"}

    def test_weighted_alpha_weights_larger_trades_more(self):
        df = pd.DataFrame([
            {"politician": "Dave", "party": "D", "type": "purchase", "amount_mid": 900_000, "alpha": 0.10},
            {"politician": "Dave", "party": "D", "type": "purchase", "amount_mid": 100_000, "alpha": 0.50},
        ])
        result = aggregate_by_politician(df)
        dave = result[result["politician"] == "Dave"].iloc[0]
        # weighted: (0.10 * 900k + 0.50 * 100k) / 1M = 0.14
        assert dave["weighted_alpha"] == pytest.approx(0.14)
