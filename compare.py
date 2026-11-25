"""買いサインが出やすいルールを、今の仮想売買と同じやり方で過去にさかのぼって比べる。

  python compare.py           # 本物のデータ（GitHub Actions で実行）
  python compare.py --sample  # 架空データで動作確認

今の仮想売買をできるだけそのまま再現します。
  - 仮想資金100万円、1銘柄20万円まで、最大5銘柄、損切り10%
  - サインの翌営業日の始値で売買、手数料など片道0.1%
  - 見る銘柄は毎週、その時点までのデータだけで東証約500銘柄から20銘柄を選び直す
    （「今」強い銘柄で過去を試すと成績が良く見えすぎるため）
比べる相手は、同じ期間に市場全体（TOPIX連動ETF 1306）をずっと持っていた場合です。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from trader import data, screen
from trader.paper import BENCH
from trader.strategies import _cross_down, _cross_up, _signal, golden_cross, rsi, rsi_values

ROOT = Path(__file__).parent
JST = timezone(timedelta(hours=9))
YEARS = 4  # 何年分を比べるか（その前の約1年は準備用のデータ）


# ---------- 比べるルール（どれも 1=買い / -1=売り / 0=何もしない） ----------
def pullback(close, level=50):
    """上昇トレンド（75日平均より上）の中で、RSIが level を下回った「押し目」で買う。"""
    up = close > close.rolling(75).mean()
    r = rsi_values(close)
    low = pd.Series(level, index=r.index)
    return _signal(_cross_down(r, low) & up, _cross_up(r, pd.Series(75, index=r.index)))


def breakout(close, days=60):
    """過去 days 日の最高値を超えたら買い、25日平均を下に割ったら売り（勢いに乗る）。"""
    high = close.shift(1).rolling(days).max()
    ma25 = close.rolling(25).mean()
    return _signal(_cross_up(close, high), _cross_down(close, ma25))


def trend(close):
    """25日平均が75日平均より上の上昇局面で、株価が25日平均を上に抜けたら買い。75日平均を割ったら売り。"""
    ma25, ma75 = close.rolling(25).mean(), close.rolling(75).mean()
    return _signal(_cross_up(close, ma25) & (ma25 > ma75), _cross_down(close, ma75))


RULES = [
    # (表示名, 説明, 関数)  ※関数が None のものは「上位銘柄を常に保有」
    ("今のルール（RSI 35/75）", "RSIが35を下回ったら買い、75を上回ったら売り",
     lambda c: rsi(c, 14, 35, 75)),
    ("RSI 40/75", "買う基準を40にゆるめる", lambda c: rsi(c, 14, 40, 75)),
    ("RSI 45/75", "買う基準を45にゆるめる", lambda c: rsi(c, 14, 45, 75)),
    ("RSI 40/70", "買う基準を40、売る基準を70に（早めに利益確定）", lambda c: rsi(c, 14, 40, 70)),
    ("押し目買い（RSI 50）", "上昇トレンド中（75日平均より上）にRSIが50を下回ったら買い、75を上回ったら売り",
     lambda c: pullback(c, 50)),
    ("押し目買い（RSI 45）", "上昇トレンド中にRSIが45を下回ったら買い、75を上回ったら売り",
     lambda c: pullback(c, 45)),
    ("押し目買い（RSI 50）・損切り7%", "押し目買い（RSI 50）の損切りを7%に早める", (lambda c: pullback(c, 50), 0.07)),
    ("ゴールデンクロス 5/25", "5日平均が25日平均を上に抜けたら買い、下に抜けたら売り",
     lambda c: golden_cross(c, 5, 25)),
    ("高値更新（60日）", "過去60日の最高値を超えたら買い、25日平均を割ったら売り", lambda c: breakout(c, 60)),
    ("上昇局面の順張り", "25日平均＞75日平均のとき、株価が25日平均を上に抜けたら買い、75日平均を割ったら売り",
     trend),
    ("勢い上位を常に保有", "選んだ20銘柄のうち点数の高い順に5銘柄を常に持ち、20銘柄から外れたら売る", None),
]


# ---------- データ ----------
def fetch(codes, years):
    import yfinance as yf

    tickers = [f"{c}.T" for c in codes]
    raw = yf.download(tickers, period=f"{years}y", auto_adjust=True, progress=False,
                      group_by="column", threads=True)
    out = {k: raw[k].copy() for k in ("Close", "Open", "Volume")}
    missing = [t for t in tickers if t not in out["Close"] or out["Close"][t].dropna().empty]
    if missing:
        print(f"{len(missing)} 銘柄を取り直します")
        again = yf.download(missing, period=f"{years}y", auto_adjust=True, progress=False,
                            group_by="column", threads=False)
        for t in missing:
            for k in out:
                col = again[k].squeeze() if len(missing) == 1 else again[k].get(t)
                if col is not None:
                    out[k][t] = col
    for df in out.values():
        df.columns = [str(c).replace(".T", "") for c in df.columns]
    close = out["Close"].dropna(how="all", axis=1)
    return close, out["Open"].reindex(columns=close.columns), out["Volume"].reindex(columns=close.columns)


def clean(df):
    """1日だけ値段が大きく飛んで翌日に戻る「データの誤り」を取り除く。"""
    r = df.pct_change(fill_method=None)
    back = df.shift(-1) / df - 1
    bad = (r.abs() > 0.3) & (back.abs() > 0.25) & (np.sign(r) != np.sign(back))
    print(f"データの誤りとして除いた値: {int(bad.sum().sum())} 個")
    return df.mask(bad).ffill(limit=1)


def sample(codes, years):
    close, volume = data.sample_close_volume(codes, years)
    return close, close.shift(1).fillna(close), volume


# ---------- 毎週の銘柄選び（screen.score と同じ条件を、その時点のデータだけで） ----------
def weekly_picks(close, volume, rules, days):
    turnover = (close * volume).rolling(20).mean() / 1e8
    ma75 = close.rolling(75).mean()
    trend_up = (close > ma75) & (ma75 > ma75.shift(20))
    vol = close.pct_change(fill_method=None).rolling(250).std() * np.sqrt(250) * 100
    mom = (close / close.shift(125) - 1) * 100
    enough = close.notna().cumsum() >= 260
    ok = enough & (turnover >= rules["min_turnover_oku"]) \
        & vol.ge(rules["min_vol"]) & vol.le(rules["max_vol"]) & (close * 100 <= rules["max_cost_100"])
    if rules.get("trend_only", True):
        ok &= trend_up
    picks = {}
    week = None
    for i, d in enumerate(close.index):
        if d < days[0] or i == 0:
            continue
        wk = d.isocalendar()[:2]
        if wk == week:
            continue
        week = wk
        prev = close.index[i - 1]  # 週の初日に、前の営業日までのデータで選ぶ
        m = ok.loc[prev]
        cand = m[m].index
        if len(cand) == 0:
            picks[d] = []
            continue
        score = mom.loc[prev, cand].rank(pct=True) * 0.6 + turnover.loc[prev, cand].rank(pct=True) * 0.4
        picks[d] = list(score.sort_values(ascending=False).head(rules["top_n"]).index)
    return picks


# ---------- 仮想売買の再現 ----------
def simulate(close, open_, signals, picks, days, capital, slots, stop, cost=0.001):
    slot = capital / slots
    cash, pos, pending = float(capital), {}, []
    equity, trades = [], []
    watch = []
    for d in days:
        watch = picks.get(d, watch)
        # 1. 前日の注文を今日の始値で約定
        for side, code in pending:
            p = open_.at[d, code]
            if not p == p:
                continue
            if side == "buy" and code not in pos:
                n = int(min(slot, cash) // (p * (1 + cost)))
                if n > 0:
                    cash -= n * p * (1 + cost)
                    pos[code] = (n, p)
            elif side == "sell" and code in pos:
                n, bp = pos.pop(code)
                cash += n * p * (1 - cost)
                trades.append(p * (1 - cost) / (bp * (1 + cost)) - 1)
        pending = []
        # 2. 翌営業日の注文
        for code, (n, bp) in pos.items():
            c = close.at[d, code]
            if not c == c:
                continue
            exit_sig = (code not in watch) if signals is None else signals[code].get(d, 0) == -1
            if exit_sig or c / bp - 1 <= -stop:
                pending.append(("sell", code))
        holding = len(pos) - len(pending)
        for code in watch:
            if holding >= slots:
                break
            if code in pos:
                continue
            buy = True if signals is None else (code in signals and signals[code].get(d, 0) == 1)
            if buy and close.at[d, code] == close.at[d, code]:
                pending.append(("buy", code))
                holding += 1
        value = cash
        for code, (n, bp) in pos.items():
            c = close.at[d, code]
            value += n * (c if c == c else bp)
        invested = (value - cash) / value
        equity.append((d, value, invested))
    eq = pd.DataFrame(equity, columns=["date", "value", "invested"]).set_index("date")
    return eq, trades


def stats(eq, trades, years):
    v = eq["value"]
    total = v.iloc[-1] / v.iloc[0] - 1
    dd = (v / v.cummax() - 1).min()
    return {"total": total * 100, "annual": ((1 + total) ** (1 / years) - 1) * 100, "dd": dd * 100,
            "trades_y": len(trades) / years, "win": np.mean([t > 0 for t in trades]) * 100 if trades else np.nan,
            "invested": eq["invested"].mean() * 100}


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    pcfg, rules = cfg["paper"], cfg["research"]["screen"]
    names = screen.universe()
    is_sample = "--sample" in sys.argv
    close, open_, volume = (sample if is_sample else fetch)(list(names) + [BENCH], YEARS + 2)
    if BENCH not in close:
        raise SystemExit("市場全体の値段（1306）が取れませんでした")
    close, open_ = clean(close), clean(open_)
    bench = close.pop(BENCH).ffill()
    med = bench.rolling(5, center=True, min_periods=1).median()
    bench = bench.mask((bench / med - 1).abs() > 0.3).ffill()  # 市場全体の値段の誤りも除く
    open_, volume = open_.drop(columns=[BENCH], errors="ignore"), volume.drop(columns=[BENCH], errors="ignore")
    end = close.index[-1]
    days = close.index[close.index >= end - timedelta(days=365 * YEARS)]
    print(f"期間 {days[0]:%Y-%m-%d}〜{end:%Y-%m-%d}、対象 {close.shape[1]} 銘柄")
    picks = weekly_picks(close, volume, rules, days)

    capital, slots, stop = pcfg["capital"], pcfg["max_positions"], pcfg["stop_loss"] / 100
    # 年ごとの区切り（直近から1年ずつ）
    cuts = [end - timedelta(days=365 * k) for k in range(YEARS, -1, -1)]
    b = bench.reindex(days).ffill()
    rows, yearly = [], {}
    bench_eq = pd.DataFrame({"value": b, "invested": 1.0})
    for label, desc, func in RULES + [("（参考）TOPIXをずっと保有", "市場全体に連動するETF（1306）を最初に買って持ち続ける", "bench")]:
        if func == "bench":
            eq, trades = bench_eq, []
        else:
            rule_stop = stop
            if isinstance(func, tuple):
                func, rule_stop = func
            sig = None if func is None else {c: func(close[c].dropna()) for c in close.columns}
            eq, trades = simulate(close, open_, sig, picks, days, capital, slots, rule_stop)
        s = stats(eq, trades, YEARS)
        s.update({"rule": label, "desc": desc})
        rows.append(s)
        yr = []
        for a, z in zip(cuts[:-1], cuts[1:]):
            part = eq["value"][(eq.index >= a) & (eq.index <= z)]
            yr.append((part.iloc[-1] / part.iloc[0] - 1) * 100 if len(part) > 1 else np.nan)
        yearly[label] = yr
        print(label, {k: round(v, 1) for k, v in s.items() if isinstance(v, float)})
    write(pd.DataFrame(rows), yearly, cuts, days, is_sample, pcfg)


def write(df, yearly, cuts, days, is_sample, pcfg):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    bench = df.iloc[-1]
    out = [f"# 買いサインが出やすいルールの比較（{now}）", ""]
    if is_sample:
        out += ["**※架空データでの動作確認です。数字に意味はありません。**", ""]
    out += [f"期間：{days[0]:%Y年%m月%d日}〜{days[-1]:%Y年%m月%d日}（約{YEARS}年）。"
            f"今の仮想売買と同じ条件（資金{pcfg['capital'] // 10000}万円・最大{pcfg['max_positions']}銘柄・"
            f"損切り{pcfg['stop_loss']}%・翌日の始値で売買・手数料など片道0.1%）で再現しました。"
            "見る20銘柄は、毎週その時点までのデータだけで選び直しています。", "",
            "## 1. 4年間の成績", "",
            "| ルール | 4年の損益 | 1年あたり | 最大の落ち込み | TOPIXとの差（1年あたり） | 売買回数/年 | 勝った売買の割合 | お金が株に入っていた割合 |",
            "|---|---|---|---|---|---|---|---|"]
    for r in df.itertuples():
        diff = r.annual - bench["annual"]
        win = "-" if r.win != r.win else f"{r.win:.0f}%"
        out.append(f"| {r.rule} | {r.total:+.1f}% | **{r.annual:+.1f}%** | {r.dd:.1f}% | {diff:+.1f} | "
                   f"{r.trades_y:.0f}回 | {win} | {r.invested:.0f}% |")
    out += ["", "## 2. 1年ごとの損益（相場の流れが変わっても通用したか）", "",
            "| ルール | " + " | ".join(f"{a:%Y/%m}〜{z:%Y/%m}" for a, z in zip(cuts[:-1], cuts[1:])) + " | TOPIXに勝った年 |",
            "|---|" + "---|" * (len(cuts)) ]
    by = yearly[bench["rule"]]
    for label, yr in yearly.items():
        wins = sum(1 for x, y in zip(yr, by) if x > y)
        out.append(f"| {label} | " + " | ".join(f"{x:+.1f}%" for x in yr) + f" | {wins}/{len(yr)} |")
    out += ["", "## ルールの中身", ""] + [f"- **{r.rule}**：{r.desc}" for r in df.itertuples()]
    out += ["", "## 注意",
            "- 「最大の落ち込み」は、資金が一番高かったときから一番下がったときまでの下落率です。",
            "- 「お金が株に入っていた割合」が低いほど、現金のまま眠っていた期間が長いことを表します。",
            "- 銘柄の一覧（約500銘柄）は「今」の東証の区分を使っているため、途中で上場廃止になった銘柄は含まれず、成績はやや良く見えがちです。",
            "- 過去の成績は将来の利益を保証しません。"]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "compare.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
