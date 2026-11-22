"""仮想売買（ペーパートレード）。本物のお金も注文も一切使いません。

毎日の流れ：
  1. 前日に出した注文を、今日の始値（寄付）で約定したことにする
  2. 今日のサインと損切りを見て、翌営業日の注文を決める
  3. 評価額と「市場全体（TOPIX連動ETF）をずっと持っていたら」の額を記録する
記録は docs/paper.json に残ります。
"""
import json

BENCH = "1306"  # TOPIX連動ETF（市場全体の目安）


def load(path, capital, today, bench_price):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"start_date": today, "capital": capital, "cash": capital, "positions": {},
            "pending": [], "trades": [], "equity": [], "last_date": None,
            "bench_units": capital / bench_price}


def save(path, state):
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def step(state, today, close, open_, signals, names, pcfg, cost_pct=0.1):
    """1日分を進める。新しくできた約定・注文の説明文のリストを返す。"""
    events = []
    if state["last_date"] == today:
        return events  # 同じ日に2回動いても二重に売買しない
    cost = cost_pct / 100

    # 1. 前日の注文を今日の始値で約定
    for order in state["pending"]:
        code = order["code"]
        price = open_.get(code)
        if price is None or price != price:  # 値段が取れない日は見送り
            continue
        name = names.get(code, code)
        if order["side"] == "buy" and code not in state["positions"]:
            slot = state["capital"] / pcfg["max_positions"]
            n = int(min(slot, state["cash"]) // (price * (1 + cost)))
            if n > 0:
                state["cash"] -= n * price * (1 + cost)
                state["positions"][code] = {"name": name, "shares": n, "buy_price": price, "buy_date": today}
                events.append(f"🟢買った {name} {n}株 @{price:,.0f}円")
        elif order["side"] == "sell" and code in state["positions"]:
            pos = state["positions"].pop(code)
            state["cash"] += pos["shares"] * price * (1 - cost)
            pnl = (price * (1 - cost) / (pos["buy_price"] * (1 + cost)) - 1) * 100
            state["trades"].append({"code": code, "name": pos["name"], "shares": pos["shares"],
                                    "buy_date": pos["buy_date"], "buy_price": pos["buy_price"],
                                    "sell_date": today, "sell_price": price, "pnl_pct": round(pnl, 2),
                                    "reason": order["reason"]})
            events.append(f"🟠売った {pos['name']} {pos['shares']}株 @{price:,.0f}円（{pnl:+.1f}%・{order['reason']}）")
    state["pending"] = []

    # 2. 翌営業日の注文を決める
    for code, pos in state["positions"].items():
        price = close.get(code)
        if price is None or price != price:
            continue
        change = (price / pos["buy_price"] - 1) * 100
        reason = None
        if signals.get(code) == -1:
            reason = "売りサイン"
        elif pcfg["stop_loss"] and change <= -pcfg["stop_loss"]:
            reason = f"損切り{pcfg['stop_loss']}%"
        elif pcfg["take_profit"] and change >= pcfg["take_profit"]:
            reason = f"利益確定{pcfg['take_profit']}%"
        if reason:
            state["pending"].append({"side": "sell", "code": code, "reason": reason})
    holding = len(state["positions"]) - sum(1 for o in state["pending"] if o["side"] == "sell")
    for code, sig in signals.items():
        if sig == 1 and code not in state["positions"] and holding < pcfg["max_positions"]:
            state["pending"].append({"side": "buy", "code": code, "reason": "買いサイン"})
            holding += 1
    for o in state["pending"]:
        word = "買い" if o["side"] == "buy" else "売り"
        events.append(f"📝明日{word}予定 {names.get(o['code'], o['code'])}（{o['reason']}）")

    # 3. 評価額を記録
    value = state["cash"] + sum(p["shares"] * (close.get(c) or p["buy_price"])
                                for c, p in state["positions"].items())
    bench = state["bench_units"] * close.get(BENCH, 0)
    state["equity"].append({"date": today, "value": round(value), "bench": round(bench)})
    state["last_date"] = today
    return events


def summary(state):
    last = state["equity"][-1]
    cap = state["capital"]
    return (f"💰仮想資金 {last['value']:,}円（{(last['value'] / cap - 1) * 100:+.1f}%）"
            f" / 市場全体をずっと保有 {(last['bench'] / cap - 1) * 100:+.1f}%")
