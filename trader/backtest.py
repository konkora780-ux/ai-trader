"""過去データでの試運転（バックテスト）。

ルール：買いサインの翌日に予算内で買えるだけ1株単位で買い、売りサインの翌日に全部売る。
プロのリスク管理として、次の3つも使えます（0 なら使わない）。
  stop_loss   : 買値から何%下がったら損切りするか
  take_profit : 買値から何%上がったら利益確定するか
  max_days    : 最長で何営業日持つか
  trailing    : 買った後の最高値から何%下がったら売るか（利益を伸ばしつつ守る）
  size        : 日ごとの「資金の何割を使うか」（値動きが荒い時は少なく買う、など）
手数料・税金は含めていません（cost_pct で片道の売買コストを仮に引けます）。
"""


def run(close, signal, budget, stop_loss=0, take_profit=0, max_days=0, cost_pct=0.0,
        trailing=0, size=None):
    close = close.dropna()
    signal = signal.reindex(close.index).fillna(0)
    cash, shares, buy_price, held, top = float(budget), 0, 0.0, 0, 0.0
    trades, peak, max_dd = [], float(budget), 0.0
    prev = 0
    for day, price in close.items():
        if shares > 0:
            held += 1
            top = max(top, price)
            change = price / buy_price - 1
            exit_now = (prev == -1
                        or (stop_loss and change <= -stop_loss / 100)
                        or (take_profit and change >= take_profit / 100)
                        or (max_days and held >= max_days)
                        or (trailing and price <= top * (1 - trailing / 100)))
            if exit_now:
                cash += shares * price * (1 - cost_pct / 100)
                trades.append(change - 2 * cost_pct / 100)
                shares = 0
        elif prev == 1:
            frac = 1.0 if size is None else float(size.get(day, 1.0))
            n = int(cash * frac // (price * (1 + cost_pct / 100)))
            if n > 0:
                shares, buy_price, held, top = n, price, 0, price
                cash -= n * price * (1 + cost_pct / 100)
        value = cash + shares * price
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1)
        prev = signal.get(day, 0)
    final = cash + shares * close.iloc[-1]
    hold = budget // close.iloc[0] * close.iloc[-1] + budget % close.iloc[0]
    wins = sum(1 for t in trades if t > 0)
    return {
        "return_pct": (final / budget - 1) * 100,
        "hold_pct": (hold / budget - 1) * 100,
        "trades": len(trades),
        "win_rate": (wins / len(trades) * 100) if trades else None,
        "max_dd_pct": max_dd * 100,
        "holding": shares > 0,
    }
