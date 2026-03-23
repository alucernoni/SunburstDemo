"""
Tests for fetch_prices.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from datetime import timedelta
import tempfile

from fetch_prices import (
    load_tickers_and_date_range,
    fetch_ticker,
    fetch_all_prices,
    load_price_series,
    get_price_on_or_after,
    BENCHMARK,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trades_csv(tmp_path, rows):
    path = tmp_path / "trades.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def make_price_csv(prices_dir, ticker, rows):
    os.makedirs(prices_dir, exist_ok=True)
    path = os.path.join(prices_dir, f"{ticker}.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def make_yfinance_df(dates, closes):
    """Returns a mock yfinance-style DataFrame with a 'Close' column."""
    idx = pd.DatetimeIndex(dates, name="Date")
    return pd.DataFrame({"Close": closes}, index=idx)


# ---------------------------------------------------------------------------
# load_tickers_and_date_range
# ---------------------------------------------------------------------------

class TestLoadTickersAndDateRange:
    def test_returns_sorted_unique_tickers(self, tmp_path):
        csv = make_trades_csv(tmp_path, {
            "ticker": ["AAPL", "MSFT", "AAPL"],
            "date":   ["2022-01-01", "2022-06-01", "2022-03-01"],
        })
        tickers, _, _ = load_tickers_and_date_range(csv)
        assert tickers == ["AAPL", "MSFT"]

    def test_start_date_is_before_earliest_trade(self, tmp_path):
        csv = make_trades_csv(tmp_path, {
            "ticker": ["AAPL"],
            "date":   ["2022-06-15"],
        })
        _, start, _ = load_tickers_and_date_range(csv)
        assert start < pd.Timestamp("2022-06-15")

    def test_end_date_is_today_or_later(self, tmp_path):
        csv = make_trades_csv(tmp_path, {
            "ticker": ["AAPL"],
            "date":   ["2022-06-15"],
        })
        _, _, end = load_tickers_and_date_range(csv)
        assert end >= pd.Timestamp.today().normalize()


# ---------------------------------------------------------------------------
# fetch_ticker
# ---------------------------------------------------------------------------

class TestFetchTicker:
    @patch("fetch_prices.yf.download")
    def test_returns_date_and_close_columns(self, mock_dl):
        mock_dl.return_value = make_yfinance_df(["2023-01-03", "2023-01-04"], [150.0, 152.0])
        df = fetch_ticker("AAPL", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"))
        assert list(df.columns) == ["date", "close"]

    @patch("fetch_prices.yf.download")
    def test_dates_normalized_to_midnight(self, mock_dl):
        mock_dl.return_value = make_yfinance_df(["2023-01-03"], [150.0])
        df = fetch_ticker("AAPL", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"))
        assert df.iloc[0]["date"] == pd.Timestamp("2023-01-03")

    @patch("fetch_prices.yf.download")
    def test_empty_response_returns_empty_dataframe(self, mock_dl):
        mock_dl.return_value = pd.DataFrame()
        df = fetch_ticker("DELISTED", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"))
        assert df.empty

    @patch("fetch_prices.yf.download")
    def test_exception_returns_empty_dataframe(self, mock_dl):
        mock_dl.side_effect = Exception("network error")
        df = fetch_ticker("BADTICKER", pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"))
        assert df.empty


# ---------------------------------------------------------------------------
# fetch_all_prices
# ---------------------------------------------------------------------------

class TestFetchAllPrices:
    @patch("fetch_prices.time.sleep")
    @patch("fetch_prices.fetch_ticker")
    def test_benchmark_always_included(self, mock_fetch, mock_sleep, tmp_path):
        mock_fetch.return_value = pd.DataFrame({"date": ["2023-01-03"], "close": [400.0]})
        prices_dir = str(tmp_path / "prices")
        fetch_all_prices(["AAPL"], pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"), prices_dir)
        fetched = [call.args[0] for call in mock_fetch.call_args_list]
        assert BENCHMARK in fetched

    @patch("fetch_prices.time.sleep")
    @patch("fetch_prices.fetch_ticker")
    def test_cached_ticker_not_fetched_again(self, mock_fetch, mock_sleep, tmp_path):
        prices_dir = str(tmp_path / "prices")
        make_price_csv(prices_dir, "AAPL", {"date": ["2023-01-03"], "close": [150.0]})
        mock_fetch.return_value = pd.DataFrame({"date": ["2023-01-03"], "close": [400.0]})

        fetch_all_prices(["AAPL"], pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"), prices_dir)
        fetched = [call.args[0] for call in mock_fetch.call_args_list]
        assert "AAPL" not in fetched

    @patch("fetch_prices.time.sleep")
    @patch("fetch_prices.fetch_ticker")
    def test_csv_written_for_each_non_empty_ticker(self, mock_fetch, mock_sleep, tmp_path):
        mock_fetch.return_value = pd.DataFrame({"date": ["2023-01-03"], "close": [150.0]})
        prices_dir = str(tmp_path / "prices")
        fetch_all_prices(["AAPL"], pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"), prices_dir)
        assert os.path.exists(os.path.join(prices_dir, "AAPL.csv"))

    @patch("fetch_prices.time.sleep")
    @patch("fetch_prices.fetch_ticker")
    def test_empty_result_not_written_to_csv(self, mock_fetch, mock_sleep, tmp_path):
        mock_fetch.return_value = pd.DataFrame(columns=["date", "close"])
        prices_dir = str(tmp_path / "prices")
        fetch_all_prices(["DELISTED"], pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"), prices_dir)
        assert not os.path.exists(os.path.join(prices_dir, "DELISTED.csv"))

    @patch("fetch_prices.time.sleep")
    @patch("fetch_prices.fetch_ticker")
    def test_sleep_called_between_fetches(self, mock_fetch, mock_sleep, tmp_path):
        mock_fetch.return_value = pd.DataFrame({"date": ["2023-01-03"], "close": [150.0]})
        prices_dir = str(tmp_path / "prices")
        fetch_all_prices(["AAPL", "MSFT"], pd.Timestamp("2023-01-01"), pd.Timestamp("2023-02-01"), prices_dir)
        assert mock_sleep.call_count >= 2


# ---------------------------------------------------------------------------
# load_price_series
# ---------------------------------------------------------------------------

class TestLoadPriceSeries:
    def test_loads_csv_sorted_by_date(self, tmp_path):
        prices_dir = str(tmp_path)
        make_price_csv(prices_dir, "AAPL", {
            "date":  ["2023-01-05", "2023-01-03", "2023-01-04"],
            "close": [155.0, 150.0, 152.0],
        })
        df = load_price_series("AAPL", prices_dir)
        assert list(df["close"]) == [150.0, 152.0, 155.0]

    def test_missing_ticker_returns_empty(self, tmp_path):
        df = load_price_series("MISSING", str(tmp_path))
        assert df.empty


# ---------------------------------------------------------------------------
# get_price_on_or_after
# ---------------------------------------------------------------------------

class TestGetPriceOnOrAfter:
    def setup_prices(self, tmp_path, ticker, rows):
        make_price_csv(str(tmp_path), ticker, rows)

    def test_returns_price_on_exact_date(self, tmp_path):
        self.setup_prices(tmp_path, "AAPL", {"date": ["2023-06-01"], "close": [180.0]})
        price = get_price_on_or_after("AAPL", pd.Timestamp("2023-06-01"), str(tmp_path))
        assert price == 180.0

    def test_returns_next_trading_day_on_weekend(self, tmp_path):
        # 2023-06-03 is Saturday → next trading day is Monday 2023-06-05
        self.setup_prices(tmp_path, "AAPL", {"date": ["2023-06-05"], "close": [182.0]})
        price = get_price_on_or_after("AAPL", pd.Timestamp("2023-06-03"), str(tmp_path))
        assert price == 182.0

    def test_returns_none_if_gap_exceeds_5_days(self, tmp_path):
        self.setup_prices(tmp_path, "AAPL", {"date": ["2023-06-10"], "close": [185.0]})
        price = get_price_on_or_after("AAPL", pd.Timestamp("2023-06-01"), str(tmp_path))
        assert price is None

    def test_returns_none_for_missing_ticker(self, tmp_path):
        price = get_price_on_or_after("MISSING", pd.Timestamp("2023-06-01"), str(tmp_path))
        assert price is None

    def test_returns_none_if_date_after_all_data(self, tmp_path):
        self.setup_prices(tmp_path, "AAPL", {"date": ["2023-01-03"], "close": [150.0]})
        price = get_price_on_or_after("AAPL", pd.Timestamp("2024-01-01"), str(tmp_path))
        assert price is None
