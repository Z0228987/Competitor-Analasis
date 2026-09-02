import math
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# ============================================================
# Configuration
# ============================================================
RUN_TIME = datetime.now(ZoneInfo("Asia/Shanghai"))
TODAY = RUN_TIME.strftime("%Y-%m-%d")

DATA_DIR = Path("data")
LATEST_FILE = DATA_DIR / "market_data_verified.csv"
HISTORY_FILE = DATA_DIR / "market_history.csv"

STOCKS = {
    "Luxshare": "002475.SZ",
    "HASCO": "600741.SS",
    "Tuopu": "601689.SS",
    "Baolong": "603197.SS",
    "BTL": "603596.SS",
    "AUMOVIO": "AMV0.F",
}

# Latest snapshot schema used by Peer Market Snapshot and Valuation Positioning.
LATEST_COLUMNS = [
    "date",
    "company",
    "ticker",
    "price",
    "market_cap",
    "pe",
    "pb",
    "currency",
    "ytd_return",
]

# Historical price schema used by Share Price Trend · Last 1 Month.
# Keep this file deliberately lightweight. Do not include market_cap, P/E, P/B or YTD.
HISTORY_COLUMNS = [
    "date",
    "company",
    "ticker",
    "price",
    "currency",
]


# ============================================================
# Helpers
# ============================================================
def clean_number(value):
    """Return a finite float, otherwise None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if math.isfinite(number) else None


def safe_info(ticker_obj, company):
    """Retrieve Yahoo company information without stopping the full update."""
    try:
        return ticker_obj.info or {}
    except Exception as exc:
        print(f"  warning: {company} info unavailable: {exc}")
        return {}


def fetch_close_history(ticker_obj, **kwargs):
    """Return valid daily Close values only."""
    frame = ticker_obj.history(
        interval="1d",
        auto_adjust=False,
        actions=False,
        repair=False,
        timeout=30,
        **kwargs,
    )

    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype="float64")

    closes = pd.to_numeric(frame["Close"], errors="coerce")
    closes = closes.replace([float("inf"), float("-inf")], pd.NA).dropna()
    return closes


def calculate_ytd_return(ticker_obj, latest_price, company):
    """Calculate return from the first valid close of the current calendar year."""
    if latest_price is None:
        return None

    try:
        closes = fetch_close_history(
            ticker_obj,
            start=f"{RUN_TIME.year}-01-01",
        )
    except Exception as exc:
        print(f"  warning: {company} YTD history unavailable: {exc}")
        return None

    if closes.empty:
        return None

    first_price = clean_number(closes.iloc[0])
    if first_price is None or first_price <= 0:
        return None

    return latest_price / first_price - 1


def build_history_rows(company, ticker, ticker_obj, currency):
    """Build the complete last-one-month daily price series for one company."""
    try:
        closes = fetch_close_history(ticker_obj, period="1mo")
    except Exception as exc:
        print(f"  warning: {company} one-month history unavailable: {exc}")
        return []

    rows = []
    for timestamp, price in closes.items():
        clean_price = clean_number(price)
        if clean_price is None:
            continue

        rows.append(
            {
                "date": pd.Timestamp(timestamp).strftime("%Y-%m-%d"),
                "company": company,
                "ticker": ticker,
                "price": round(clean_price, 2),
                "currency": currency,
            }
        )

    return rows


# ============================================================
# Main update
# ============================================================
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    latest_records = []
    history_records = []

    for company, ticker in STOCKS.items():
        print("=" * 60)
        print(f"Processing {company} ({ticker})")

        ticker_obj = yf.Ticker(ticker)
        info = safe_info(ticker_obj, company)

        currency = info.get("currency") or info.get("financialCurrency")

        # Latest valid close. dropna() inside fetch_close_history prevents an
        # incomplete exchange row, such as AUMOVIO Close = NaN, from being used.
        try:
            one_year_closes = fetch_close_history(ticker_obj, period="1y")
        except Exception as exc:
            print(f"  warning: {company} one-year history unavailable: {exc}")
            one_year_closes = pd.Series(dtype="float64")

        latest_price = (
            clean_number(one_year_closes.iloc[-1])
            if not one_year_closes.empty
            else None
        )

        ytd_return = calculate_ytd_return(ticker_obj, latest_price, company)

        market_cap = clean_number(info.get("marketCap"))
        pe = clean_number(info.get("trailingPE"))
        if pe is None:
            pe = clean_number(info.get("forwardPE"))
        pb = clean_number(info.get("priceToBook"))

        latest_records.append(
            {
                "date": TODAY,
                "company": company,
                "ticker": ticker,
                "price": round(latest_price, 2) if latest_price is not None else None,
                "market_cap": round(market_cap) if market_cap is not None else None,
                "pe": round(pe, 6) if pe is not None else None,
                "pb": round(pb, 6) if pb is not None else None,
                "currency": currency,
                "ytd_return": round(ytd_return, 10) if ytd_return is not None else None,
            }
        )

        # Fetch every valid daily close in the last month.
        history_records.extend(
            build_history_rows(
                company=company,
                ticker=ticker,
                ticker_obj=ticker_obj,
                currency=currency,
            )
        )

        print(
            "  latest result: "
            f"price={latest_price}, market_cap={market_cap}, "
            f"pe={pe}, pb={pb}, currency={currency}, ytd={ytd_return}"
        )

        # Small pause reduces the chance of rapid-request throttling.
        time.sleep(1)

    # --------------------------------------------------------
    # Write latest snapshot
    # --------------------------------------------------------
    latest_df = pd.DataFrame(latest_records, columns=LATEST_COLUMNS)
    valid_latest_prices = pd.to_numeric(
        latest_df["price"], errors="coerce"
    ).notna().sum()

    if valid_latest_prices == 0:
        raise RuntimeError(
            "Yahoo returned no valid latest prices. Existing CSV files were not overwritten."
        )

    latest_df.to_csv(LATEST_FILE, index=False)

    # --------------------------------------------------------
    # Write one-month history
    # --------------------------------------------------------
    history_df = pd.DataFrame(history_records, columns=HISTORY_COLUMNS)

    if history_df.empty:
        raise RuntimeError(
            "Yahoo returned no valid one-month history. Existing market_history.csv was not overwritten."
        )

    # Normalize fields and remove duplicate company/date rows.
    history_df["date"] = history_df["date"].astype(str)
    history_df["company"] = history_df["company"].astype(str)
    history_df["ticker"] = history_df["ticker"].astype(str)
    history_df["price"] = pd.to_numeric(history_df["price"], errors="coerce")
    history_df = history_df.dropna(subset=["date", "company", "price"])

    history_df = history_df.drop_duplicates(
        subset=["date", "company"],
        keep="last",
    )

    history_df = history_df.sort_values(
        by=["date", "company"],
        kind="stable",
    )

    # Important: overwrite market_history.csv with the complete current
    # one-month series. This removes the old snapshot schema containing
    # market_cap, P/E, P/B and YTD fields.
    history_df.to_csv(HISTORY_FILE, index=False)

    print("=" * 60)
    print(f"Market data updated at {RUN_TIME.isoformat()}")
    print(
        f"{LATEST_FILE}: {len(latest_df)} rows, "
        f"{valid_latest_prices} valid latest prices"
    )
    print(
        f"{HISTORY_FILE}: {len(history_df)} rows, "
        f"{history_df['date'].nunique()} trading dates, "
        f"{history_df['company'].nunique()} companies"
    )
    print(f"History columns: {', '.join(HISTORY_COLUMNS)}")


if __name__ == "__main__":
    main()
