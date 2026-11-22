"""株価データの取得。"""
import numpy as np
import pandas as pd


def fetch_prices(codes, years):
    """証券コードのリストから、日ごとの終値の表を返す（列＝銘柄コード）。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]  # 東証銘柄は末尾に .T をつける
    raw = yf.download(tickers, period=f"{years + 1}y", auto_adjust=True,
                      progress=False, group_by="column")
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close.columns = [str(c).replace(".T", "") for c in close.columns]
    return close.dropna(how="all")


def sample_prices(codes, years, seed=0):
    """通信できない環境での動作確認用に、それらしい架空の株価を作る。"""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=250 * (years + 1))
    data = {}
    for i, c in enumerate(codes):
        steps = rng.normal(0.0003, 0.018, len(days))
        data[c] = (1000 + 500 * i) * np.exp(np.cumsum(steps))
    return pd.DataFrame(data, index=days).round(1)
