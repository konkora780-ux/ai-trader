"""プロの工夫が本当に効くかを、過去データで確かめる実験。

  python experiments.py           # 本物のデータ（GitHub Actions で実行）
  python experiments.py --sample  # 架空データで動作確認

今の仮想売買のルール（RSI 35/75・損切り10%）を「基本」として、工夫を1つずつ足して比べます。
対象は東証の大型・中型株（約500銘柄）すべて。銘柄を選んでから試すと成績が良く見えがちなので、全部で試します。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from trader import backtest, data, screen
from trader.paper import BENCH
from trader.strategies import rsi

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))

VARIANTS = [
    ("基本（今のルール）", {}),
    ("＋地合い判定", {"market": True}),
    ("＋出来高の確認", {"volume": True}),
    ("＋トレーリングストップ8%", {"trailing": 8}),
    ("＋トレーリングストップ12%", {"trailing": 12}),
    ("＋値動きに合わせて買う量を調整", {"sizing": True}),
    ("＋地合い判定＋トレーリング12%", {"market": True, "trailing": 12}),
    ("＋地合い判定＋値動き調整", {"market": True, "sizing": True}),
]
EXPLAIN = {
    "＋地合い判定": "市場全体（TOPIX）が75日平均より下＝下げ相場の間は、新しく買わない",
    "＋出来高の確認": "買いサインの日の出来高が、普段（20日平均）の1.5倍以上のときだけ買う",
    "＋トレーリングストップ8%": "買った後の一番高い値段から8%下がったら売る（利益を守る）",
    "＋トレーリングストップ12%": "同じく12%下がったら売る（少しゆとりを持たせる）",
    "＋値動きに合わせて買う量を調整": "値動きが荒い銘柄・時期ほど少なく買う（年率25%を目安に、資金の3〜10割）",
}


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    p = cfg["params"]["rsi"]
    sl = cfg["paper"]["stop_loss"]
    years, test_years, cost = 4, 1, 0.1
    names = screen.universe()
    sample = "--sample" in sys.argv
    load = data.sample_close_volume if sample else data.fetch_close_volume
    close, volume = load(list(names) + [BENCH], years + 1)
    if BENCH not in close:
        raise SystemExit("市場全体の値段（1306）が取れませんでした")
    mkt = close[BENCH].dropna()
    market_ok = (mkt > mkt.rolling(75).mean()).reindex(close.index).ffill().fillna(False)

    end = close.index[-1]
    periods = {"学習（4年前〜1年前）": (end - timedelta(days=365 * years), end - timedelta(days=365 * test_years)),
               "検証（直近1年）": (end - timedelta(days=365 * test_years), end)}
    rows = []
    for label, opt in VARIANTS:
        for pname, (a, b) in periods.items():
            rets, dds, trades, holds = [], [], [], []
            for code in names:
                if code not in close:
                    continue
                c = close[code].dropna()
                if len(c) < 300:
                    continue
                sig = rsi(c, **p)
                buy = sig == 1
                if opt.get("market"):
                    buy &= market_ok.reindex(c.index).fillna(False)
                if opt.get("volume"):
                    v = volume[code].reindex(c.index)
                    buy &= v > v.rolling(20).mean() * 1.5
                sig = sig.where((sig != 1) | buy, 0)
                size = None
                if opt.get("sizing"):
                    vol = c.pct_change().rolling(20).std() * np.sqrt(250)
                    size = (0.25 / vol).clip(0.3, 1.0).fillna(1.0)
                part = c[(c.index >= a) & (c.index <= b)]
                if len(part) < 60:
                    continue
                bt = backtest.run(part, sig, 1_000_000, stop_loss=sl, cost_pct=cost,
                                  trailing=opt.get("trailing", 0), size=size)
                rets.append(bt["return_pct"]); dds.append(bt["max_dd_pct"])
                trades.append(bt["trades"]); holds.append(bt["hold_pct"])
            r, d = np.median(rets), np.median(dds)  # 一部のおかしなデータに引きずられないよう中央値
            rows.append({"工夫": label, "期間": pname, "平均損益%": r, "平均の最大落ち込み%": d,
                         "効率（損益÷落ち込み）": r / abs(d) if d else np.nan,
                         "プラスで終えた銘柄%": np.mean([x > 0 for x in rets]) * 100,
                         "売買回数/銘柄": np.median(trades), "ずっと保有%": np.median(holds), "銘柄数": len(rets)})
    df = pd.DataFrame(rows)
    write(df, sample, p, sl)


def write(df, sample, p, sl):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    out = [f"# プロの工夫の効果検証（{now}）", ""]
    if sample:
        out += ["**※架空データでの動作確認です。数字に意味はありません。**", ""]
    out += [f"基本ルール：RSIが{p['buy_below']}を下回ったら買い・{p['sell_above']}を上回ったら売り・損切り{sl}%。"
            "東証の大型・中型株すべてで1銘柄ずつ試した結果の中央値（真ん中の値）です。手数料など片道0.1%を差し引いています。", ""]
    for pname in df["期間"].unique():
        sub = df[df["期間"] == pname]
        base = sub.iloc[0]
        out += [f"## {pname}（ずっと保有した場合の中央値 {base['ずっと保有%']:+.1f}%）", "",
                "| 工夫 | 損益 | 基本との差 | 最大の落ち込み | 効率 | プラスで終えた銘柄 | 売買回数 |",
                "|---|---|---|---|---|---|---|"]
        for r in sub.itertuples(index=False):
            out.append(f"| {r[0]} | {r[2]:+.1f}% | {r[2] - base['平均損益%']:+.1f} | {r[3]:.1f}% | "
                       f"{r[4]:.2f} | {r[5]:.0f}% | {r[6]:.1f}回 |")
        out.append("")
    out += ["## それぞれの工夫の中身", ""] + [f"- **{k}**：{v}" for k, v in EXPLAIN.items()]
    out += ["", "## 注意",
            "- 「効率」は、損益を最大の落ち込みで割った値です。大きいほど、怖い思いを少なく利益を出せたことを表します。",
            "- 決算発表の直前に買わない工夫は、日本株の過去の決算日データが無料では安定して手に入らないため、今回は試していません。",
            "- 過去の成績は将来の利益を保証しません。"]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "experiments.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
