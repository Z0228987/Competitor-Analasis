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
    "AUMOVIO":"AMV0.F"
}

records = []

for company, ticker in stocks.items():

    try:
        tk = yf.Ticker(ticker)

        info = tk.info

        hist = tk.history(period="1y")

        latest_price = hist["Close"].iloc[-1]

        first_price = hist["Close"].iloc[0]

        ytd_return = (
            latest_price / first_price - 1
        )

        records.append({
            "date": today,
            "company": company,
            "ticker": ticker,
            "price": round(latest_price, 2),
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "currency": info.get("currency"),
            "ytd_return": ytd_return
        })

    except Exception as e:
        print(f"{company} failed: {e}")

df = pd.DataFrame(records)

Path("data").mkdir(exist_ok=True)

df.to_csv(
    "data/market_data_verified.csv",
    index=False
)

history_file = Path(
    "data/market_history.csv"
)

if history_file.exists():

    old = pd.read_csv(history_file)

    history = pd.concat(
        [old, df],
        ignore_index=True
    )

else:

    history = df

history.to_csv(
    history_file,
    index=False
)

print("Market data updated.")
