"""株価データの取得。"""
import numpy as np
import pandas as pd


def fetch_prices(codes, years):
    """証券コードのリストから、日ごとの（終値, 始値）の表を返す（列＝銘柄コード）。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]  # 東証銘柄は末尾に .T をつける
    raw = yf.download(tickers, period=f"{years + 1}y", auto_adjust=True,
                      progress=False, group_by="column")
    out = []
    for col in ("Close", "Open"):
        df = raw[col]
        if isinstance(df, pd.Series):
            df = df.to_frame(tickers[0])
        df.columns = [str(c).replace(".T", "") for c in df.columns]
        out.append(df.dropna(how="all"))
    return out[0], out[1].reindex(out[0].index)


def sample_prices(codes, years, seed=0):
    """通信できない環境での動作確認用に、それらしい架空の株価を作る。"""
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=250 * (years + 1))
    data = {}
    for c in codes:
        rng = np.random.default_rng(seed * 10000 + int(c))  # 銘柄ごとに毎回同じ値動き
        steps = rng.normal(0.0003, 0.018, len(days))
        data[c] = (500 + int(c) % 5000) * np.exp(np.cumsum(steps))
    return pd.DataFrame(data, index=days).round(1)


def sample_ohlc(codes, years, seed=0, days_back=0):
    close = sample_prices(codes, years, seed)
    if days_back:
        close = close.iloc[:-days_back]
    return close, (close.shift(1) * 1.002).fillna(close)


def fetch_close_volume(codes, years):
    """多数の銘柄の終値と出来高をまとめて取る（列＝銘柄コード）。"""
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]
    raw = yf.download(tickers, period=f"{years}y", auto_adjust=True, progress=False,
                      group_by="column", threads=True)
    close, volume = raw["Close"].copy(), raw["Volume"].copy()
    # 同時取得で取りこぼした銘柄は、1つずつ取り直す
    missing = [t for t in tickers if t not in close or close[t].dropna().empty]
    if missing:
        print(f"{len(missing)} 銘柄を取り直します")
        again = yf.download(missing, period=f"{years}y", auto_adjust=True, progress=False,
                            group_by="column", threads=False)
        for t in missing:
            if len(missing) == 1:
                close[t], volume[t] = again["Close"].squeeze(), again["Volume"].squeeze()
            elif t in again["Close"]:
                close[t], volume[t] = again["Close"][t], again["Volume"][t]
    for df in (close, volume):
        df.columns = [str(c).replace(".T", "") for c in df.columns]
    return close.dropna(how="all", axis=1), volume


def sample_close_volume(codes, years, seed=1):
    close = sample_prices(codes, years - 1, seed)
    rng = np.random.default_rng(seed)
    volume = pd.DataFrame(rng.integers(1e5, 5e6, close.shape), index=close.index, columns=close.columns)
    return close, volume
