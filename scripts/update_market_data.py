import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

# Use Shanghai date for the daily snapshot key.
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

COLUMNS = [
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


def clean_number(value):
    """Return a normal Python number or None, never NaN/inf."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def safe_info(ticker_obj):
    """Yahoo fundamentals can fail independently of price history."""
    try:
        return ticker_obj.info or {}
    except Exception as exc:
        print(f"  warning: info unavailable: {exc}")
        return {}


def get_close_series(ticker_obj):
    """Fetch one year of daily closes and remove incomplete Yahoo rows."""
    history = ticker_obj.history(
        period="1y",
        interval="1d",
        auto_adjust=False,
        actions=False,
        repair=True,
        keepna=False,
        timeout=30,
    )

    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype="float64")

    closes = pd.to_numeric(history["Close"], errors="coerce")
    closes = closes.replace([float("inf"), float("-inf")], pd.NA).dropna()
    return closes


def get_ytd_return(ticker_obj, latest_price):
    """Calculate calendar-year return from first valid close in current year."""
    if latest_price is None:
        return None

    year_start = f"{RUN_TIME.year}-01-01"
    try:
        ytd = ticker_obj.history(
            start=year_start,
            interval="1d",
            auto_adjust=False,
            actions=False,
            repair=True,
            keepna=False,
            timeout=30,
        )
        if ytd is None or ytd.empty or "Close" not in ytd.columns:
            return None
        closes = pd.to_numeric(ytd["Close"], errors="coerce").dropna()
        first_price = clean_number(closes.iloc[0]) if not closes.empty else None
        if first_price is None or first_price <= 0:
            return None
        return latest_price / first_price - 1
    except Exception as exc:
        print(f"  warning: YTD history unavailable: {exc}")
        return None


def fetch_company(company, ticker):
    print("=" * 60)
    print(f"Processing {company} ({ticker})")

    ticker_obj = yf.Ticker(ticker)
    info = safe_info(ticker_obj)

    closes = get_close_series(ticker_obj)
    latest_price = clean_number(closes.iloc[-1]) if not closes.empty else None
    latest_market_date = str(closes.index[-1]) if not closes.empty else "N/A"

    ytd_return = get_ytd_return(ticker_obj, latest_price)

    market_cap = clean_number(info.get("marketCap"))
    pe = clean_number(info.get("trailingPE"))
    if pe is None:
        pe = clean_number(info.get("forwardPE"))
    pb = clean_number(info.get("priceToBook"))
    currency = info.get("currency") or info.get("financialCurrency")

    print(f"  latest valid market date: {latest_market_date}")
    print(f"  price={latest_price}, market_cap={market_cap}, pe={pe}, pb={pb}, currency={currency}, ytd={ytd_return}")

    # Always retain a row for every configured company, even if Yahoo omits a field.
    return {
        "date": TODAY,
        "company": company,
        "ticker": ticker,
        "price": round(latest_price, 2) if latest_price is not None else None,
        "market_cap": round(market_cap) if market_cap is not None else None,
        "pe": round(pe, 4) if pe is not None else None,
        "pb": round(pb, 4) if pb is not None else None,
        "currency": currency,
        "ytd_return": round(ytd_return, 8) if ytd_return is not None else None,
    }


def read_history(path):
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS)
    try:
        old = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=COLUMNS)

    for column in COLUMNS:
        if column not in old.columns:
            old[column] = None
    return old[COLUMNS]


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for company, ticker in STOCKS.items():
        try:
            records.append(fetch_company(company, ticker))
        except Exception as exc:
            print(f"{company} failed: {type(exc).__name__}: {exc}")
            records.append({
                "date": TODAY,
                "company": company,
                "ticker": ticker,
                "price": None,
                "market_cap": None,
                "pe": None,
                "pb": None,
                "currency": None,
                "ytd_return": None,
            })
        time.sleep(1)

    latest = pd.DataFrame(records, columns=COLUMNS)

    # Do not replace the latest file if every price request failed.
    valid_prices = pd.to_numeric(latest["price"], errors="coerce").notna().sum()
    if valid_prices == 0:
        raise RuntimeError("Yahoo returned no valid prices for any configured ticker; existing CSV files were not overwritten.")

    latest.to_csv(LATEST_FILE, index=False)

    history = read_history(HISTORY_FILE)
    history = pd.concat([history, latest], ignore_index=True)
    history["date"] = history["date"].astype(str)
    history["company"] = history["company"].astype(str)

    # Re-running the workflow on the same Shanghai date replaces that day's row.
    history = history.drop_duplicates(subset=["date", "company"], keep="last")
    history = history.sort_values(["date", "company"], kind="stable")
    history.to_csv(HISTORY_FILE, index=False)

    print("=" * 60)
    print(f"Market data updated at {RUN_TIME.isoformat()}")
    print(f"Latest rows: {len(latest)}; valid prices: {valid_prices}")
    print(f"History rows: {len(history)}")


if __name__ == "__main__":
    main()
