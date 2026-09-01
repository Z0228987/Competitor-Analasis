import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

today = datetime.now().strftime("%Y-%m-%d")

stocks = {
    "Luxshare": "002475.SZ",
    "HASCO": "600741.SS",
    "Tuopu": "601689.SS",
    "Baolong": "603197.SS",
    "BTL": "603596.SS",
    "AUMOVIO": "AMV0.F"
}

records = []

for company, ticker in stocks.items():

    print(f"Processing {company} ({ticker})")
   

    try:

        tk = yf.Ticker(ticker)

        info = tk.info

        hist = tk.history(period="1y")

        print(hist.tail())

        latest_price = None
        ytd_return = None

        if not hist.empty and "Close" in hist.columns:

            latest_price = float(hist["Close"].iloc[-1])

            first_price = float(hist["Close"].iloc[0])

            if first_price > 0:
                ytd_return = (
                    latest_price / first_price - 1
                )

        records.append({

            "date": today,
            "company": company,
            "ticker": ticker,

            "price": round(latest_price, 2)
            if latest_price else None,

            "market_cap":
                info.get("marketCap"),

            "pe":
                info.get("trailingPE"),

            "pb":
                info.get("priceToBook"),

            "currency":
                info.get("currency"),

            "ytd_return":
                ytd_return
        })

    except Exception as e:

        print(
            f"{company} failed: {e}"
        )

df = pd.DataFrame(records)

Path("data").mkdir(
    exist_ok=True
)

# 最新快照
df.to_csv(
    "data/market_data_verified.csv",
    index=False
)

history_file = Path(
    "data/market_history.csv"
)

# 历史库
if history_file.exists() and history_file.stat().st_size > 0:

    try:

        old = pd.read_csv(
            history_file
        )

        history = pd.concat(
            [old, df],
            ignore_index=True
        )

    except:

        history = df

else:

    history = df

# 去重
history = history.drop_duplicates(
    subset=["date", "company"],
    keep="last"
)

history.to_csv(
    history_file,
    index=False
)

print(
    "Market data updated."
)
