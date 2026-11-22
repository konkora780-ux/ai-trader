"""過去データでの試運転（バックテスト）。

ルール：買いサインの翌日に予算内で買えるだけ1株単位で買い、売りサインの翌日に全部売る。
手数料・税金は含めていません（プチ株・少額売買のイメージ）。
"""


def run(close, signal, budget):
    close = close.dropna()
    signal = signal.reindex(close.index).fillna(0)
    cash, shares, buy_price = float(budget), 0, 0.0
    trades = []
    prev = 0
    for day, price in close.items():
        if prev == 1 and shares == 0:
            n = int(cash // price)
            if n > 0:
                shares, buy_price, cash = n, price, cash - n * price
        elif prev == -1 and shares > 0:
            cash += shares * price
            trades.append(price / buy_price - 1)
            shares = 0
        prev = signal.get(day, 0)
    final = cash + shares * close.iloc[-1]
    hold = budget // close.iloc[0] * close.iloc[-1] + budget % close.iloc[0]
    wins = sum(1 for t in trades if t > 0)
    return {
        "return_pct": (final / budget - 1) * 100,
        "hold_pct": (hold / budget - 1) * 100,
        "trades": len(trades),
        "win_rate": (wins / len(trades) * 100) if trades else None,
        "holding": shares > 0,
    }
