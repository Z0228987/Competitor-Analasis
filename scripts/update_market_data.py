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
    "NASN": "2261.HK", # Yahoo港股推荐不带前置0，优先用2261.HK
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

def fetch_ticker_history_with_retry(ticker_obj, period="1y", max_retry=3):
    """带重试拉取K线，最多3次，指数退避"""
    for attempt in range(max_retry):
        try:
            frame = ticker_obj.history(
                interval="1d",
                auto_adjust=False,
                actions=False,
                repair=False,
                timeout=30,
                period=period
            )
            if not (frame is None or frame.empty or "Close" not in frame.columns):
                closes = pd.to_numeric(frame["Close"], errors="coerce")
                closes = closes.replace([float("inf"), float("-inf")], pd.NA).dropna()
                return closes
        except Exception as exc:
            wait = (2 ** attempt) + random.uniform(0.5,1.2)
            print(f"  Retry {attempt+1}/{max_retry}, wait {wait:.1f}s, error: {exc}")
            time.sleep(wait)
    print("  Max retry reached, history fetch failed")
    return pd.Series(dtype="float64")

def calculate_ytd_return_from_series(full_closes, latest_price, company):
    """从已经下载好的1年K线切片计算YTD，不再重复请求"""
    if latest_price is None or full_closes.empty:
        return None
    start_year = RUN_TIME.year
    # 构建当年1月1日，并转为K线时区
    ytd_start_naive = pd.Timestamp(f"{start_year}-01-01")
    ytd_start = ytd_start_naive.tz_localize(full_closes.index.tz)

    # NASN新股保护：YTD起始不能早于上市日
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
    """从已下载的1年K线，切片最近1个月数据，不再重复请求"""
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

def safe_get_fastinfo(fast_info_obj, attr_name, default=None):
    """安全读取fast_info属性，捕获AttributeError"""
    try:
        val = getattr(fast_info_obj, attr_name)
        return val
    except (AttributeError, KeyError):
        return default
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
            # 优先fast_info，安全读取属性
            fast_info = {}
            try:
                fast_info = ticker_obj.fast_info
            except Exception as exc:
                print(f"  warning: fast_info unavailable {exc}")
                fast_info = None

            # 货币兜底：NASN固定HKD
            currency = None
            if company == "NASN":
                currency = "HKD"
            if fast_info is not None and currency is None:
                currency = safe_get_fastinfo(fast_info, "currency")

            market_cap = None
            pe = None
            pb = None
            if fast_info is not None:
                market_cap = clean_number(safe_get_fastinfo(fast_info, "market_cap"))
                pe = clean_number(safe_get_fastinfo(fast_info, "trailingPE"))
                if pe is None:
                    pe = clean_number(safe_get_fastinfo(fast_info, "forwardPE"))
                pb = clean_number(safe_get_fastinfo(fast_info, "priceToBook"))

            # 只拉一次1年K线，后面YTD和历史全部切片复用
            one_year_closes = fetch_ticker_history_with_retry(ticker_obj, period="1y")

            latest_price = (
                clean_number(one_year_closes.iloc[-1])
                if not one_year_closes.empty
                else None
            )
            ytd_return = calculate_ytd_return_from_series(one_year_closes, latest_price, company)

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
            print(f"  WARNING: Failed to process {company}({ticker}), skip this stock: {exc}")
            # 失败也写入一行记录，全部字段为空
            latest_records.append({
                "date": TODAY,
                "company": company,
                "ticker": ticker,
                "price": None,
                "market_cap": None,
                "pe": None,
                "pb": None,
                "currency": "HKD" if company == "NASN" else None,
                "ytd_return": None,
            })

        # 随机sleep，防爬虫识别
        time.sleep(random.uniform(1.2,2.5))
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
