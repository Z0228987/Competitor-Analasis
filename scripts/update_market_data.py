import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

RUN_TIME = datetime.now(ZoneInfo('Asia/Shanghai'))
TODAY = RUN_TIME.strftime('%Y-%m-%d')
DATA_DIR = Path('data')
LATEST_FILE = DATA_DIR / 'market_data_verified.csv'
HISTORY_FILE = DATA_DIR / 'market_history.csv'
STOCKS = {'Luxshare':'002475.SZ','HASCO':'600741.SS','Tuopu':'601689.SS','Baolong':'603197.SS','BTL':'603596.SS','AUMOVIO':'AMV0.F'}
LATEST_COLUMNS=['date','company','ticker','price','market_cap','pe','pb','currency','ytd_return']
HISTORY_COLUMNS=['date','company','ticker','price','currency']

def n(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError): return None

def history(tk,**kwargs):
    h=tk.history(interval='1d',auto_adjust=False,actions=False,repair=False,timeout=30,**kwargs)
    if h is None or h.empty or 'Close' not in h.columns:return pd.Series(dtype='float64')
    return pd.to_numeric(h['Close'],errors='coerce').dropna()

def safe_csv(path,columns):
    if not path.exists() or path.stat().st_size==0:return pd.DataFrame(columns=columns)
    try:d=pd.read_csv(path)
    except pd.errors.EmptyDataError:return pd.DataFrame(columns=columns)
    for c in columns:
        if c not in d.columns:d[c]=None
    return d[columns]

def main():
    DATA_DIR.mkdir(exist_ok=True)
    latest=[]; month=[]
    for company,ticker in STOCKS.items():
        print(f'Processing {company} ({ticker})')
        tk=yf.Ticker(ticker)
        try:info=tk.info or {}
        except Exception as e:print('info warning:',e);info={}
        closes=history(tk,period='1y')
        last=n(closes.iloc[-1]) if not closes.empty else None
        ytd=history(tk,start=f'{RUN_TIME.year}-01-01')
        first=n(ytd.iloc[0]) if not ytd.empty else None
        ret=(last/first-1) if last is not None and first and first>0 else None
        pe=n(info.get('trailingPE')) or n(info.get('forwardPE'))
        currency=info.get('currency') or info.get('financialCurrency')
        latest.append({'date':TODAY,'company':company,'ticker':ticker,'price':round(last,2) if last is not None else None,'market_cap':n(info.get('marketCap')),'pe':pe,'pb':n(info.get('priceToBook')),'currency':currency,'ytd_return':ret})
        one_month=tk.history(period='1mo',interval='1d',auto_adjust=False,actions=False,repair=False,timeout=30)
        if one_month is not None and not one_month.empty and 'Close' in one_month.columns:
            c=pd.to_numeric(one_month['Close'],errors='coerce').dropna()
            for dt,px in c.items():
                month.append({'date':pd.Timestamp(dt).strftime('%Y-%m-%d'),'company':company,'ticker':ticker,'price':round(float(px),2),'currency':currency})
    latest_df=pd.DataFrame(latest,columns=LATEST_COLUMNS)
    if pd.to_numeric(latest_df.price,errors='coerce').notna().sum()==0:raise RuntimeError('No valid prices; existing files were not overwritten.')
    latest_df.to_csv(LATEST_FILE,index=False)
    old=safe_csv(HISTORY_FILE,HISTORY_COLUMNS)
    hist=pd.concat([old,pd.DataFrame(month,columns=HISTORY_COLUMNS)],ignore_index=True)
    hist=hist.drop_duplicates(['date','company'],keep='last').sort_values(['date','company'])
    hist.to_csv(HISTORY_FILE,index=False)
    print(f'Latest rows: {len(latest_df)}; one-month history rows: {len(hist)}')
if __name__=='__main__':main()
