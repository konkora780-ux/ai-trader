"""AIトレーダー 段階1：分析・LINE通知。

使い方:
  python main.py           # 本物の株価で実行
  python main.py --sample  # 架空の株価で動作確認（ネット不要）
  python main.py --always  # サインがなくてもLINEに送る（通知の試し用）
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from trader import backtest, data, notify, report
from trader.strategies import STRATEGIES

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    stocks = cfg["watchlist"]
    years = cfg["backtest"]["years"]
    codes = [str(s["code"]) for s in stocks]
    prices = data.sample_prices(codes, years) if "--sample" in sys.argv else data.fetch_prices(codes, years)
    start = prices.index[-1] - timedelta(days=365 * years)

    results, alerts = [], []
    for key in cfg["strategies"]:
        title, func = STRATEGIES[key]
        params = cfg.get("params", {}).get(key, {})
        rows = []
        for s in stocks:
            code = str(s["code"])
            if code not in prices or prices[code].dropna().empty:
                print(f"{code} の株価が取れませんでした。コードを確認してください。")
                continue
            close = prices[code].dropna()
            sig = func(close, **params)
            today = int(sig.iloc[-1])
            bt = backtest.run(close[close.index >= start], sig, cfg["backtest"]["budget"])
            rows.append({"code": code, "name": s["name"], "price": close.iloc[-1],
                         "signal": today, "bt": bt, "close": close})
            if today != 0:
                alerts.append(f"{'🔴買い' if today == 1 else '🔵売り'} {s['name']}（{code}）"
                              f" {close.iloc[-1]:,.0f}円 [{title}]")
        results.append((title, rows))

    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report.build(results, updated, years), encoding="utf-8")
    print(f"結果画面を作りました: {out}")

    if alerts or not cfg["notify"]["only_when_signal"] or "--always" in sys.argv:
        body = "\n".join(alerts) if alerts else "今日はサインがありません。"
        notify.send_line(f"📈 AIトレーダー {updated}\n{body}")
    else:
        print("今日はサインがないため、LINEは送りません。")


if __name__ == "__main__":
    main()
