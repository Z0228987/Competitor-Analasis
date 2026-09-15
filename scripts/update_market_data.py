import math
import time
import random
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

# NASN 拿森科技上市日期
NASN_LIST_DATE = "2026-08-07"

STOCKS = {
    "Luxshare": "002475.SZ",
    "HASCO": "600741.SS",
    "Tuopu": "601689.SS",
    "Baolong": "603197.SS",
    "BTL": "603596.SS",
    "AUMOVIO": "AMV0.F",
    "NASN": "2261.HK",  # Yahoo 港股不带前导 0
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
    """Retrieve Yahoo company info without stopping the full update.
    Returns a dict (possibly empty) instead of raising."""
    try:
        return ticker_obj.info or {}
    except Exception as exc:
        print(f"  warning: {company} info unavailable: {exc}")
        return {}


def fetch_ticker_history_with_retry(ticker_obj, period="1y", max_retry=3):
    """带重试拉取 K 线，最多 3 次，指数退避"""
    for attempt in range(max_retry):
        try:
            frame = ticker_obj.history(
                interval="1d",
                auto_adjust=False,
                actions=False,
                repair=False,
                timeout=30,
                period=period,
            )
            if not (frame is None or frame.empty or "Close" not in frame.columns):
                closes = pd.to_numeric(frame["Close"], errors="coerce")
                closes = closes.replace(
                    [float("inf"), float("-inf")], pd.NA
                ).dropna()
                return closes
        except Exception as exc:
            wait = (2 ** attempt) + random.uniform(0.5, 1.2)
            print(f"  Retry {attempt + 1}/{max_retry}, wait {wait:.1f}s, error: {exc}")
            time.sleep(wait)
    print("  Max retry reached, history fetch failed")
    return pd.Series(dtype="float64")


def calculate_ytd_return_from_series(full_closes, latest_price, company):
    """从已经下载好的 1 年 K 线切片计算 YTD，不再重复请求"""
    if latest_price is None or full_closes.empty:
        return None
    start_year = RUN_TIME.year
    # 构建当年 1 月 1 日，并转为 K 线时区
    ytd_start_naive = pd.Timestamp(f"{start_year}-01-01")
    ytd_start = ytd_start_naive.tz_localize(full_closes.index.tz)

    # NASN 新股保护：YTD 起始不能早于上市日
    if company == "NASN":
        list_dt_naive = pd.Timestamp(NASN_LIST_DATE)
        list_dt = list_dt_naive.tz_localize(full_closes.index.tz)
        ytd_start = max(ytd_start, list_dt)

    ytd_closes = full_closes[full_closes.index >= ytd_start]
    if ytd_closes.empty:
        return None
    first_price = clean_number(ytd_closes.iloc[0])
    if first_price is None or first_price <= 0:
        return None
    return latest_price / first_price - 1


def build_history_rows_from_series(company, ticker, full_closes, currency):
    """从已下载的 1 年 K 线，切片最近 1 个月数据，不再重复请求"""
    if full_closes.empty:
        return []
    run_tz = pd.Timestamp(RUN_TIME).tz_convert(full_closes.index.tz)
    one_month_start = run_tz - pd.Timedelta(days=30)
    recent_closes = full_closes[full_closes.index >= one_month_start]
    rows = []
    for timestamp, price in recent_closes.items():
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
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")
    normalized = normalized.dropna(subset=["date", "company", "price"])
    normalized = normalized[
        normalized["date"].str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)
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
        try:
            ticker_obj = yf.Ticker(ticker)

            # 用 .info 拿 PE / PB / marketCap / currency（fast_info 没有 PE/PB）
            info = safe_info(ticker_obj, company)

            # 货币兜底：NASN 固定 HKD
            currency = info.get("currency") or info.get("financialCurrency")
            if company == "NASN" and not currency:
                currency = "HKD"

            market_cap = clean_number(info.get("marketCap"))
            pe = clean_number(info.get("trailingPE"))
            if pe is None:
                pe = clean_number(info.get("forwardPE"))
            pb = clean_number(info.get("priceToBook"))

            # 只拉一次 1 年 K 线，后面 YTD 和历史全部切片复用
            one_year_closes = fetch_ticker_history_with_retry(
                ticker_obj, period="1y"
            )

            latest_price = (
                clean_number(one_year_closes.iloc[-1])
                if not one_year_closes.empty
                else None
            )
            ytd_return = calculate_ytd_return_from_series(
                one_year_closes, latest_price, company
            )

            company_history = build_history_rows_from_series(
                company=company,
                ticker=ticker,
                full_closes=one_year_closes,
                currency=currency,
            )

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
                    "pe": (round(pe, 6) if pe is not None else None),
                    "pb": (round(pb, 6) if pb is not None else None),
                    "currency": currency,
                    "ytd_return": (
                        round(ytd_return, 10) if ytd_return is not None else None
                    ),
                }
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
        except Exception as exc:
            print(
                f"  WARNING: Failed to process {company}({ticker}), "
                f"skip this stock: {exc}"
            )
            latest_records.append(
                {
                    "date": TODAY,
                    "company": company,
                    "ticker": ticker,
                    "price": None,
                    "market_cap": None,
                    "pe": None,
                    "pb": None,
                    "currency": "HKD" if company == "NASN" else None,
                    "ytd_return": None,
                }
            )

        # 随机 sleep，防爬虫识别
        time.sleep(random.uniform(1.2, 2.5))

    # --------------------------------------------------------
    # Write latest snapshot
    # --------------------------------------------------------
    latest_df = pd.DataFrame(latest_records, columns=LATEST_COLUMNS)
    valid_latest_prices = (
        pd.to_numeric(latest_df["price"], errors="coerce").notna().sum()
    )
    if valid_latest_prices == 0:
        raise RuntimeError(
            "Yahoo returned no valid latest prices. "
            "Existing CSV files were not overwritten."
        )
    latest_df.to_csv(LATEST_FILE, index=False)

    # --------------------------------------------------------
    # Merge and write cumulative history
    # --------------------------------------------------------
    new_history_df = pd.DataFrame(
        new_history_records, columns=HISTORY_COLUMNS
    )
    new_history_df = normalize_history(new_history_df)

    existing_history_df = read_existing_history()
    history_df = pd.concat([existing_history_df, new_history_df], ignore_index=True)
    # 新下载的值覆盖同公司同日期的旧值
    history_df = history_df.drop_duplicates(
        subset=["date", "company"], keep="last"
    )
    history_df = history_df.sort_values(
        by=["date", "company"], kind="stable"
    ).reset_index(drop=True)
    history_df.to_csv(HISTORY_FILE, index=False)

    print("=" * 60)
    print(f"Market data updated at {RUN_TIME.isoformat()}")
    print(
        f"{LATEST_FILE}: {len(latest_df)} rows, "
        f"{valid_latest_prices} valid latest prices"
    )
    print(
        f"New downloaded history: {len(new_history_df)} rows, "
        f"{new_history_df['date'].nunique()} trading dates"
    )
    print(
        f"{HISTORY_FILE}: {len(history_df)} cumulative rows, "
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
#（注：内容由AI生成）
