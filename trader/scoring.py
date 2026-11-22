"""買いサインの「質」を点数にする（無料・データだけで判断）。

プロのスイングトレーダーが見る5つの観点を1点ずつ数えます（最大5点）。
  1. 上昇トレンド中の押し目か（終値が75日平均より上）
  2. 地合いが良いか（市場全体＝TOPIX連動ETFが75日平均より上）
  3. 投げ売りが出たか（出来高が20日平均の1.5倍以上）
  4. 十分に売られたか（RSIが30未満）
  5. 急落の途中ではないか（20日間で15%を超えて下がっていない）
"""
from trader.strategies import rsi_values

LABELS = ["上昇トレンド中", "地合い良好", "出来高急増", "深い売られすぎ", "急落ではない"]


def parts(c, v, market_ok):
    """各観点を True/False の表（列＝観点）で返す。"""
    import pandas as pd
    return pd.DataFrame({
        LABELS[0]: c > c.rolling(75).mean(),
        LABELS[1]: market_ok.reindex(c.index).fillna(False).astype(bool),
        LABELS[2]: v > v.rolling(20).mean() * 1.5,
        LABELS[3]: rsi_values(c) < 30,
        LABELS[4]: c / c.shift(20) - 1 > -0.15,
    })


def score_series(c, v, market_ok):
    return parts(c, v, market_ok).sum(axis=1)


def explain_today(c, v, market_ok):
    """今日の点数と、満たした・満たさなかった観点の説明を返す。"""
    row = parts(c, v, market_ok).iloc[-1]
    ok = [k for k, x in row.items() if x]
    ng = [k for k, x in row.items() if not x]
    return int(row.sum()), ok, ng
