"""
Tests for run_pipeline.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, call
from run_pipeline import main


def run_with_args(args):
    with patch("sys.argv", ["run_pipeline.py"] + args):
        main()


class TestRunPipeline:
    @patch("run_pipeline.run_build_hierarchy")
    @patch("run_pipeline.run_calculate_alpha")
    @patch("run_pipeline.run_fetch_prices")
    @patch("run_pipeline.run_fetch_trades")
    def test_all_steps_run_by_default(self, mock_trades, mock_prices, mock_alpha, mock_hierarchy):
        run_with_args([])
        mock_trades.assert_called_once()
        mock_prices.assert_called_once()
        mock_alpha.assert_called_once()
        mock_hierarchy.assert_called_once()

    @patch("run_pipeline.run_build_hierarchy")
    @patch("run_pipeline.run_calculate_alpha")
    @patch("run_pipeline.run_fetch_prices")
    @patch("run_pipeline.run_fetch_trades")
    @patch("os.path.exists", return_value=True)
    def test_skip_fetch_skips_steps_1_and_2(self, mock_exists, mock_trades, mock_prices, mock_alpha, mock_hierarchy):
        run_with_args(["--skip-fetch"])
        mock_trades.assert_not_called()
        mock_prices.assert_not_called()
        mock_alpha.assert_called_once()
        mock_hierarchy.assert_called_once()

    @patch("run_pipeline.run_build_hierarchy")
    @patch("run_pipeline.run_calculate_alpha")
    @patch("run_pipeline.run_fetch_prices")
    @patch("run_pipeline.run_fetch_trades")
    @patch("os.path.exists", return_value=False)
    def test_skip_fetch_exits_if_no_cached_data(self, mock_exists, mock_trades, mock_prices, mock_alpha, mock_hierarchy):
        with pytest.raises(SystemExit):
            run_with_args(["--skip-fetch"])
        mock_alpha.assert_not_called()
        mock_hierarchy.assert_not_called()

    @patch("run_pipeline.run_build_hierarchy")
    @patch("run_pipeline.run_calculate_alpha")
    @patch("run_pipeline.run_fetch_prices")
    @patch("run_pipeline.run_fetch_trades")
    def test_steps_run_in_order(self, mock_trades, mock_prices, mock_alpha, mock_hierarchy):
        call_order = []
        mock_trades.side_effect    = lambda: call_order.append("trades")
        mock_prices.side_effect    = lambda: call_order.append("prices")
        mock_alpha.side_effect     = lambda: call_order.append("alpha")
        mock_hierarchy.side_effect = lambda: call_order.append("hierarchy")

        run_with_args([])
        assert call_order == ["trades", "prices", "alpha", "hierarchy"]
