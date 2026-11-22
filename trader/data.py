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


def fetch_close_volume(codes, years):
    """多数の銘柄の終値と出来高をまとめて取る（列＝銘柄コード）。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]
    raw = yf.download(tickers, period=f"{years}y", auto_adjust=True, progress=False,
                      group_by="column", threads=True)
    close, volume = raw["Close"], raw["Volume"]
    for df in (close, volume):
        df.columns = [str(c).replace(".T", "") for c in df.columns]
    return close.dropna(how="all", axis=1), volume


def sample_close_volume(codes, years, seed=1):
    close = sample_prices(codes, years - 1, seed)
    rng = np.random.default_rng(seed)
    volume = pd.DataFrame(rng.integers(1e5, 5e6, close.shape), index=close.index, columns=close.columns)
    return close, volume
