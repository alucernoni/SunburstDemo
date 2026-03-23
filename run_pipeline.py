"""
run_pipeline.py

Runs the full data pipeline in order:
  1. fetch_trades.py   → data/trades.csv
  2. fetch_prices.py   → data/prices/<TICKER>.csv
  3. calculate_alpha.py → data/alphas.csv
  4. build_hierarchy.py → public/hierarchy.json

Usage:
  python run_pipeline.py              # run all steps
  python run_pipeline.py --skip-fetch # skip steps 1 & 2 (reuse cached data)
"""

import argparse
import sys
import os

# Ensure pipeline/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pipeline"))

import fetch_trades
import fetch_prices
import calculate_alpha
import build_hierarchy
import pandas as pd


def run_fetch_trades():
    print("\n=== Step 1/4: Fetching trades ===")
    fetch_trades.main()


def run_fetch_prices():
    print("\n=== Step 2/4: Fetching prices ===")
    fetch_prices.main()


def run_calculate_alpha():
    print("\n=== Step 3/4: Calculating alpha ===")
    calculate_alpha.main()


def run_build_hierarchy():
    print("\n=== Step 4/4: Building hierarchy ===")
    build_hierarchy.main()


def main():
    parser = argparse.ArgumentParser(description="Run the congressional sunburst data pipeline.")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip steps 1 & 2 (trade + price fetching) and reuse cached data/trades.csv and data/prices/.",
    )
    args = parser.parse_args()

    if args.skip_fetch:
        if not os.path.exists("data/trades.csv"):
            print("Error: --skip-fetch specified but data/trades.csv not found. Run without --skip-fetch first.")
            sys.exit(1)
        if not os.path.exists("data/prices"):
            print("Error: --skip-fetch specified but data/prices/ not found. Run without --skip-fetch first.")
            sys.exit(1)
        print("Skipping fetch steps (using cached data).")
    else:
        run_fetch_trades()
        run_fetch_prices()

    run_calculate_alpha()
    run_build_hierarchy()

    print("\nPipeline complete. Output: public/hierarchy.json")


if __name__ == "__main__":
    main()
