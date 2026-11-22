"""売買ルール。どれも「1=買い / -1=売り / 0=何もしない」を日ごとに返す。

新しいルールを足すときは、関数を1つ書いて STRATEGIES に名前を登録するだけです。
"""
import pandas as pd


def _cross_up(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_down(a, b):
    return (a < b) & (a.shift(1) >= b.shift(1))


def _signal(buy, sell):
    s = pd.Series(0, index=buy.index)
    s[buy.fillna(False)] = 1
    s[sell.fillna(False)] = -1
    return s


def golden_cross(close, short=5, long=25):
    s, l = close.rolling(short).mean(), close.rolling(long).mean()
    return _signal(_cross_up(s, l), _cross_down(s, l))


def rsi_values(close, period=14):
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def rsi(close, period=14, buy_below=30, sell_above=70):
    r = rsi_values(close, period)
    low, high = pd.Series(buy_below, index=r.index), pd.Series(sell_above, index=r.index)
    return _signal(_cross_down(r, low), _cross_up(r, high))


def bollinger(close, period=20, width=2.0):
    mid = close.rolling(period).mean()
    lower = mid - width * close.rolling(period).std()
    return _signal(_cross_down(close, lower), _cross_up(close, mid))


STRATEGIES = {
    "golden_cross": ("ゴールデンクロス", golden_cross),
    "rsi": ("RSI（売られすぎ・買われすぎ）", rsi),
    "bollinger": ("ボリンジャーバンド", bollinger),
}
