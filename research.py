"""銘柄の絞り込み ＋ 成績の良いルール探し。

  python research.py           # 本物のデータ（GitHub Actions で実行）
  python research.py --sample  # 架空データで動作確認

過去の一部（学習期間）で良かった設定を選び、その後の期間（検証期間）で本当に通用したかを確かめます。
「過去にだけ都合よく合わせた設定」を選んでしまう失敗（過剰最適化）を避けるためです。
"""
import itertools
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

from trader import backtest, data, screen
from trader.strategies import STRATEGIES

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))

GRID = {
    "golden_cross": [{"short": s, "long": l} for s in (5, 10, 20) for l in (25, 50, 75) if s < l],
    "rsi": [{"period": 14, "buy_below": b, "sell_above": s} for b in (25, 30, 35) for s in (65, 70, 75)],
    "bollinger": [{"period": 20, "width": w} for w in (1.5, 2.0, 2.5)],
}
RISK = [
    {"label": "損切りなし", "stop_loss": 0, "take_profit": 0, "max_days": 0},
    {"label": "損切り5%・利確10%・最長20日", "stop_loss": 5, "take_profit": 10, "max_days": 20},
    {"label": "損切り8%・利確20%・最長40日", "stop_loss": 8, "take_profit": 20, "max_days": 40},
]


def fmt_params(p):
    return "・".join(f"{k}={v}" for k, v in p.items())


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    rcfg = cfg["research"]
    names = screen.universe()
    sample = "--sample" in sys.argv
    load = data.sample_close_volume if sample else data.fetch_close_volume
    close, volume = load(list(names), rcfg["years"] + 1)

    picks = screen.score(close, volume, rcfg["screen"])
    print(f"候補 {len(picks)} 銘柄")
    split = close.index[-1] - timedelta(days=365 * rcfg["test_years"])
    start = close.index[-1] - timedelta(days=365 * rcfg["years"])
    budget, cost = rcfg["budget"], rcfg["cost_pct"]

    rows = []
    for (key, grid), risk in itertools.product(GRID.items(), RISK):
        title, func = STRATEGIES[key]
        for params in grid:
            res = {"rule": title, "params": fmt_params(params), "risk": risk["label"]}
            r_args = {k: risk[k] for k in ("stop_loss", "take_profit", "max_days")}
            for period, (a, b) in {"train": (start, split), "test": (split, close.index[-1])}.items():
                rets, holds, dds, trades = [], [], [], 0
                for code in picks["code"]:
                    c = close[code].dropna()
                    sig = func(c, **params)
                    part = c[(c.index >= a) & (c.index <= b)]
                    if len(part) < 60:
                        continue
                    bt = backtest.run(part, sig, budget, cost_pct=cost, **r_args)
                    rets.append(bt["return_pct"]); holds.append(bt["hold_pct"])
                    dds.append(bt["max_dd_pct"]); trades += bt["trades"]
                res[f"{period}_ret"] = sum(rets) / len(rets)
                res[f"{period}_hold"] = sum(holds) / len(holds)
                res[f"{period}_dd"] = sum(dds) / len(dds)
                res[f"{period}_win"] = sum(1 for x, h in zip(rets, holds) if x > h) / len(rets) * 100
                res[f"{period}_trades"] = trades / len(rets)
            rows.append(res)

    df = pd.DataFrame(rows).sort_values("train_ret", ascending=False)
    write_report(df, picks, names, rcfg, sample)


def write_report(df, picks, names, rcfg, sample):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    train_y = rcfg["years"] - rcfg["test_years"]
    lines = [f"# 銘柄の絞り込みとルール探しの結果（{now}）", ""]
    if sample:
        lines += ["**※架空データでの動作確認です。数字に意味はありません。**", ""]
    lines += ["## 1. 絞り込んだ候補銘柄", "",
              "| 順位 | 銘柄 | 株価 | 100株の金額 | 売買代金/日 | 半年の上昇率 | 値動きの大きさ(年率) |",
              "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(picks.itertuples(), 1):
        lines.append(f"| {i} | {names.get(r.code, r.code)}（{r.code}） | {r.price:,.0f}円 | "
                     f"{r.cost_100 / 1e4:,.0f}万円 | {r.turnover:,.0f}億円 | {r.momentum:+.1f}% | {r.volatility:.0f}% |")
    lines += ["", f"## 2. ルールの成績（学習{train_y}年で上位10、検証は直近{rcfg['test_years']}年）", "",
              "候補銘柄すべてで同じ設定を使ったときの平均です。手数料・すべり（想定より不利な値段で約定すること）"
              f"として片道{rcfg['cost_pct']}%を差し引いています。", "",
              "| ルール | 数字 | リスク管理 | 学習:損益 | 学習:ずっと保有 | **検証:損益** | **検証:ずっと保有** | 検証:最大の落ち込み | 検証:保有に勝った銘柄の割合 | 検証:売買回数/銘柄 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in df.head(10).itertuples():
        lines.append(f"| {r.rule} | {r.params} | {r.risk} | {r.train_ret:+.1f}% | {r.train_hold:+.1f}% | "
                     f"**{r.test_ret:+.1f}%** | **{r.test_hold:+.1f}%** | {r.test_dd:.1f}% | {r.test_win:.0f}% | {r.test_trades:.1f} |")
    lines += ["", "## 注意",
              "- 過去の成績は将来の利益を保証しません。",
              "- 「ずっと保有」は、同じ期間に最初に買ってそのまま持っていた場合の損益です。これに勝てないルールは、手間をかける意味が薄いと考えます。",
              "- 候補銘柄は「今」の条件で選んでいるため、過去の成績はやや良く見えがちです（後から見て強かった銘柄を選んでいるため）。"]
    out = ROOT / "docs" / "research.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    df.to_csv(ROOT / "docs" / "research_all.csv", index=False, encoding="utf-8-sig")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
