"""AIトレーダー 段階1：分析・LINE通知。

使い方:
  python main.py           # 本物の株価で実行
  python main.py --sample  # 架空の株価で動作確認（ネット不要）
  python main.py --always  # サインがなくてもLINEに送る（通知の試し用）
  ※仮想売買の記録は docs/paper.json（--sample のときは docs/paper_sample.json）
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from trader import backtest, data, notify, paper, report, scoring
from trader.strategies import STRATEGIES

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    stocks = cfg["watchlist"]
    auto = ROOT / "docs" / "watchlist.yaml"
    if cfg.get("watchlist_source") == "auto" and auto.exists():
        stocks = yaml.safe_load(auto.read_text(encoding="utf-8"))["watchlist"]
        print(f"自動で選んだ {len(stocks)} 銘柄を使います")
    years = cfg["backtest"]["years"]
    names = {str(s["code"]): s["name"] for s in stocks}
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    sample = "--sample" in sys.argv
    paper_path = docs / ("paper_sample.json" if sample else "paper.json")
    held = paper.load(paper_path, 0, "", 1)["positions"] if paper_path.exists() else {}
    for c, p in held.items():
        names.setdefault(c, p["name"])
    codes = list(dict.fromkeys([str(s["code"]) for s in stocks] + list(held) + [paper.BENCH]))
    back = int(sys.argv[sys.argv.index("--days-back") + 1]) if "--days-back" in sys.argv else 0
    prices, opens, volumes = (data.sample_ohlc(codes, years, days_back=back) if sample
                     else data.fetch_prices(codes, years))
    start = prices.index[-1] - timedelta(days=365 * years)

    # 東証が休み（土日・祝日・年末年始）の日は、今日の値段が出ないので何もしない
    today_jst = datetime.now(JST).date()
    if not sample and "--always" not in sys.argv and prices.index[-1].date() != today_jst:
        print(f"今日（{today_jst}）は東証の取引がないため、判定・仮想売買・通知を休みます。")
        return

    results, alerts, combined, ai_log = [], [], {}, []
    for key in cfg["strategies"]:
        title, func = STRATEGIES[key]
        params = cfg.get("params", {}).get(key, {})
        rows = []
        for code in codes:
            if code == paper.BENCH:
                continue
            if code not in prices or prices[code].dropna().empty:
                print(f"{code} の株価が取れませんでした。コードを確認してください。")
                continue
            close = prices[code].dropna()
            sig = func(close, **params)
            today = int(sig.iloc[-1]) if sig.index[-1] == prices.index[-1] else 0
            if today:
                combined[code] = -1 if -1 in (today, combined.get(code)) else 1
            if code not in names or code in held and code not in [str(s["code"]) for s in stocks]:
                continue  # 監視対象外の保有銘柄は、仮想売買の判定だけに使う
            bt = backtest.run(close[close.index >= start], sig, cfg["backtest"]["budget"])
            rows.append({"code": code, "name": names[code], "price": close.iloc[-1],
                         "signal": today, "bt": bt, "close": close})
            if today != 0:
                alerts.append(f"{'🔴買い' if today == 1 else '🔵売り'} {names[code]}（{code}）"
                              f" {close.iloc[-1]:,.0f}円 [{title}]")
            if today == 1 and paper.BENCH in prices:
                m = prices[paper.BENCH].dropna()
                pts, ok, ng = scoring.explain_today(close, volumes[code].reindex(close.index),
                                                    m > m.rolling(75).mean())
                alerts.append(f"　📊プロ目線の点数 {pts}/5　◎{'・'.join(ok) or 'なし'}"
                              f"　△{'・'.join(ng) or 'なし'}")
        results.append((title, rows))

    # 仮想売買
    day = prices.index[-1].strftime("%Y-%m-%d")
    last_close = prices.iloc[-1].to_dict()
    last_open = opens.iloc[-1].to_dict()
    state = paper.load(paper_path, cfg["paper"]["capital"], day, last_close[paper.BENCH])
    events = paper.step(state, day, last_close, last_open, combined, names, cfg["paper"])
    state.setdefault("ai_log", []).extend(ai_log)
    state["ai_log"] = state["ai_log"][-30:]
    paper.save(paper_path, state)

    updated = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    out = docs / "index.html"
    out.write_text(report.build(results, updated, years, state), encoding="utf-8")
    print(f"結果画面を作りました: {out}")

    if alerts or events or not cfg["notify"]["only_when_signal"] or "--always" in sys.argv:
        body = "\n".join(alerts) if alerts else "今日はサインがありません。"
        extra = ("\n\n【仮想売買】\n" + "\n".join(events)) if events else "\n"
        notify.send_line(f"📈 AIトレーダー {updated}\n{body}{extra}\n{paper.summary(state)}")
    else:
        print("今日はサインも仮想売買もないため、LINEは送りません。")


if __name__ == "__main__":
    main()
