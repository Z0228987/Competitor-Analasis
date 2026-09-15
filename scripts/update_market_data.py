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
    "NASN":"02261.HK",
}

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
    closes = closes.replace(
        [float("inf"), float("-inf")],
        pd.NA,
    ).dropna()

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
    """
    Download the latest one-month series.

    Existing history is preserved later by merging the downloaded rows
    with market_history.csv.
    """
    try:
        closes = fetch_close_history(
            ticker_obj,
            period="1mo",
        )
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


def normalize_history(frame):
    """Normalize market-history structure before merging."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    normalized = frame.copy()

    for column in HISTORY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    normalized = normalized[HISTORY_COLUMNS]

    normalized["date"] = normalized["date"].astype(str)
    normalized["company"] = normalized["company"].astype(str)
    normalized["ticker"] = normalized["ticker"].astype(str)
    normalized["currency"] = normalized["currency"].astype(str)

    normalized["price"] = pd.to_numeric(
        normalized["price"],
        errors="coerce",
    )

    normalized = normalized.dropna(
        subset=["date", "company", "price"]
    )

    normalized = normalized[
        normalized["date"].str.match(
            r"^\d{4}-\d{2}-\d{2}$",
            na=False,
        )
    ]

    return normalized


def read_existing_history():
    """Read existing history without failing the entire update."""
    if not HISTORY_FILE.exists():
        print("Existing market history not found. A new file will be created.")
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    try:
        existing = pd.read_csv(HISTORY_FILE)
    except Exception as exc:
        print(f"warning: existing market history could not be read: {exc}")
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    existing = normalize_history(existing)

    print(
        f"Existing history loaded: {len(existing)} rows, "
        f"{existing['date'].nunique()} dates, "
        f"{existing['company'].nunique()} companies"
    )

    return existing


# ============================================================
# Main update
# ============================================================
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    latest_records = []
    new_history_records = []

    for company, ticker in STOCKS.items():
        print("=" * 60)
        print(f"Processing {company} ({ticker})")

        ticker_obj = yf.Ticker(ticker)
        info = safe_info(ticker_obj, company)

        currency = (
            info.get("currency")
            or info.get("financialCurrency")
        )

        try:
            one_year_closes = fetch_close_history(
                ticker_obj,
                period="1y",
            )
        except Exception as exc:
            print(
                f"  warning: {company} "
                f"one-year history unavailable: {exc}"
            )
            one_year_closes = pd.Series(dtype="float64")

        latest_price = (
            clean_number(one_year_closes.iloc[-1])
            if not one_year_closes.empty
            else None
        )

        ytd_return = calculate_ytd_return(
            ticker_obj,
            latest_price,
            company,
        )

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
                "price": (
                    round(latest_price, 2)
                    if latest_price is not None
                    else None
                ),
                "market_cap": (
                    round(market_cap)
                    if market_cap is not None
                    else None
                ),
                "pe": (
                    round(pe, 6)
                    if pe is not None
                    else None
                ),
                "pb": (
                    round(pb, 6)
                    if pb is not None
                    else None
                ),
                "currency": currency,
                "ytd_return": (
                    round(ytd_return, 10)
                    if ytd_return is not None
                    else None
                ),
            }
        )

        company_history = build_history_rows(
            company=company,
            ticker=ticker,
            ticker_obj=ticker_obj,
            currency=currency,
        )

        new_history_records.extend(company_history)

        print(
            "  latest result: "
            f"price={latest_price}, "
            f"market_cap={market_cap}, "
            f"pe={pe}, "
            f"pb={pb}, "
            f"currency={currency}, "
            f"ytd={ytd_return}, "
            f"history_rows={len(company_history)}"
        )

        time.sleep(1)

    # --------------------------------------------------------
    # Write latest snapshot
    # --------------------------------------------------------
    latest_df = pd.DataFrame(
        latest_records,
        columns=LATEST_COLUMNS,
    )

    valid_latest_prices = pd.to_numeric(
        latest_df["price"],
        errors="coerce",
    ).notna().sum()

    if valid_latest_prices == 0:
        raise RuntimeError(
            "Yahoo returned no valid latest prices. "
            "Existing CSV files were not overwritten."
        )

    latest_df.to_csv(
        LATEST_FILE,
        index=False,
    )

    # --------------------------------------------------------
    # Merge and write cumulative history
    # --------------------------------------------------------
    new_history_df = pd.DataFrame(
        new_history_records,
        columns=HISTORY_COLUMNS,
    )

    new_history_df = normalize_history(new_history_df)

    if new_history_df.empty:
        raise RuntimeError(
            "Yahoo returned no valid recent history. "
            "Existing market_history.csv was not overwritten."
        )

    existing_history_df = read_existing_history()

    history_df = pd.concat(
        [
            existing_history_df,
            new_history_df,
        ],
        ignore_index=True,
    )

    # New downloaded values take priority over existing values
    # for the same company and date.
    history_df = history_df.drop_duplicates(
        subset=["date", "company"],
        keep="last",
    )

    history_df = history_df.sort_values(
        by=["date", "company"],
        kind="stable",
    ).reset_index(drop=True)

    history_df.to_csv(
        HISTORY_FILE,
        index=False,
    )

    print("=" * 60)
    print(f"Market data updated at {RUN_TIME.isoformat()}")

    print(
        f"{LATEST_FILE}: "
        f"{len(latest_df)} rows, "
        f"{valid_latest_prices} valid latest prices"
    )

    print(
        f"New downloaded history: "
        f"{len(new_history_df)} rows, "
        f"{new_history_df['date'].nunique()} trading dates"
    )

    print(
        f"{HISTORY_FILE}: "
        f"{len(history_df)} cumulative rows, "
        f"{history_df['date'].nunique()} trading dates, "
        f"{history_df['company'].nunique()} companies"
    )

    if not history_df.empty:
        company_ranges = (
            history_df.groupby("company")["date"]
            .agg(["min", "max", "count"])
            .sort_index()
        )

        print("History ranges by company:")
        print(company_ranges.to_string())

    print(f"History columns: {', '.join(HISTORY_COLUMNS)}")


if __name__ == "__main__":
    main()
