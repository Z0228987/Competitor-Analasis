import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

today = datetime.now().strftime("%Y-%m-%d")

stocks = {
    "Luxshare": "002475.SZ",
    "HASCO": "600741.SS",
    "Tuopu": "601689.SS",
    "Baolong": "603197.SS",
    "BTL": "603596.SS",
    "AUMOVIO": "AMV0.F"
}


def clean_number(value):
    try:
        value = float(value)

        if math.isnan(value):
            return None

        return value

    except:
        return None


records = []

for company, ticker in stocks.items():

    try:

        print("=" * 50)
        print(f"Processing {company} ({ticker})")

        tk = yf.Ticker(ticker)

        try:
            info = tk.info
        except:
            info = {}

        hist = tk.history(
            period="1y",
            interval="1d",
            auto_adjust=False,
            actions=False
        )

        latest_price = None
        ytd_return = None

        if (
            hist is not None
            and not hist.empty
            and "Close" in hist.columns
        ):

            close_prices = (
                pd.to_numeric(
                    hist["Close"],
                    errors="coerce"
                )
                .dropna()
            )

            if len(close_prices) > 0:

                latest_price = float(
                    close_prices.iloc[-1]
                )

                first_price = float(
                    close_prices.iloc[0]
                )

                if first_price > 0:

                    ytd_return = (
                        latest_price
                        / first_price
                        - 1
                    )

        market_cap = clean_number(
            info.get("marketCap")
        )

        pe = clean_number(
            info.get("trailingPE")
        )

        if pe is None:

            pe = clean_number(
                info.get("forwardPE")
            )

        pb = clean_number(
            info.get("priceToBook")
        )

        currency = (
            info.get("currency")
            or info.get("financialCurrency")
        )

        print(
            f"price={latest_price}, "
            f"market_cap={market_cap}, "
            f"pe={pe}, "
            f"pb={pb}"
        )

        records.append({

            "date": today,

            "company": company,

            "ticker": ticker,

            "price":
                round(latest_price, 2)
                if latest_price is not None
                else None,

            "market_cap": market_cap,

            "pe": pe,

            "pb": pb,

            "currency": currency,

            "ytd_return": ytd_return

        })

    except Exception as e:

        print(
            f"{company} failed: {e}"
        )

        records.append({

            "date": today,

            "company": company,

            "ticker": ticker,

            "price": None,

            "market_cap": None,

            "pe": None,

            "pb": None,

            "currency": None,

            "ytd_return": None

        })


df = pd.DataFrame(records)

Path("data").mkdir(
    exist_ok=True
)

# Latest snapshot
df.to_csv(
    "data/market_data_verified.csv",
    index=False
)

history_file = Path(
    "data/market_history.csv"
)

if (
    history_file.exists()
    and history_file.stat().st_size > 0
):

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

history = history.drop_duplicates(
    subset=[
        "date",
        "company"
    ],
    keep="last"
)

history.to_csv(
    history_file,
    index=False
)

print(
    "Market data updated."
)
