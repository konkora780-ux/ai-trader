"""スマホでも見やすい結果画面（docs/index.html）を作る。"""
import html

SIGNAL_LABEL = {1: ("買いサイン", "buy"), -1: ("売りサイン", "sell"), 0: ("サインなし", "none")}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1d2330;--sub:#667085;--line:#e4e7ec;
--buy:#c0392b;--buybg:#fdecea;--sell:#1f6fb2;--sellbg:#e8f1fb;--spark:#475467}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--text:#e8eaee;
--sub:#98a2b3;--line:#2e343e;--buy:#ff7a6b;--buybg:#3a1f1c;--sell:#6fb3ff;--sellbg:#1a2a3d;--spark:#aab3c2}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:system-ui,-apple-system,"Hiragino Sans","Yu Gothic UI",sans-serif;line-height:1.6}
main{max-width:960px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2em 0}
h2{font-size:1.1rem;margin:1.6em 0 .6em;border-left:4px solid var(--sub);padding-left:8px}
.meta{color:var(--sub);font-size:.85rem}.grid{display:grid;gap:12px;
grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.name{font-weight:600}.code{color:var(--sub);font-size:.8rem}.price{font-size:1.2rem;font-weight:600}
.badge{font-size:.8rem;padding:2px 10px;border-radius:999px;white-space:nowrap}
.buy{background:var(--buybg);color:var(--buy)}.sell{background:var(--sellbg);color:var(--sell)}
.none{background:var(--line);color:var(--sub)}svg{width:100%;height:48px;display:block;margin:6px 0}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0;font-size:.85rem}
dt{color:var(--sub)}table{width:100%;border-collapse:collapse;margin-top:12px;font-size:.85rem}
th,td{text-align:left;padding:4px 6px;border-bottom:1px solid var(--line)}th{color:var(--sub);font-weight:500}dd{margin:0;text-align:right}.note{color:var(--sub);font-size:.8rem;margin-top:24px}
"""


def _spark(series):
    s = series.dropna().tail(120)
    lo, hi = s.min(), s.max()
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * 300 / max(len(s) - 1, 1):.1f},{46 - (v - lo) / rng * 44:.1f}"
                   for i, v in enumerate(s))
    return (f'<svg viewBox="0 0 300 48" preserveAspectRatio="none" aria-label="直近の値動き">'
            f'<polyline fill="none" stroke="var(--spark)" stroke-width="1.5" points="{pts}"/></svg>')


def _pct(v):
    return "—" if v is None else f"{v:+.1f}%"


def _paper(state):
    if not state or not state.get("equity"):
        return ""
    last, cap = state["equity"][-1], state["capital"]
    ret, bench = (last["value"] / cap - 1) * 100, (last["bench"] / cap - 1) * 100
    hist = [e["value"] for e in state["equity"]]
    rows = "".join(
        f"<tr><td>{html.escape(p['name'])}</td><td>{p['shares']}株</td><td>{p['buy_price']:,.0f}円</td>"
        f"<td>{p['buy_date']}</td></tr>" for p in state["positions"].values()) or \
        "<tr><td colspan='4'>まだ持っている銘柄はありません</td></tr>"
    trades = "".join(
        f"<tr><td>{html.escape(t['name'])}</td><td>{t['sell_date']}</td><td>{t['pnl_pct']:+.1f}%</td>"
        f"<td>{html.escape(t['reason'])}</td></tr>" for t in reversed(state["trades"][-10:])) or \
        "<tr><td colspan='4'>まだ売った銘柄はありません</td></tr>"
    pend = "、".join(f"{o['code']}を{'買い' if o['side'] == 'buy' else '売り'}" for o in state["pending"]) or "なし"
    wins = sum(1 for t in state["trades"] if t["pnl_pct"] > 0)
    rate = f"{wins / len(state['trades']) * 100:.0f}%" if state["trades"] else "—"
    import pandas as pd
    spark = _spark(pd.Series(hist)) if len(hist) > 1 else ""
    return (f"<h2>仮想売買の成績（{state['start_date']}開始・本物のお金は使っていません）</h2>"
            f"<div class='card'><div class='top'><div><div class='code'>評価額</div>"
            f"<div class='price'>{last['value']:,} 円</div></div><span class='badge {'buy' if ret >= 0 else 'sell'}'>"
            f"{ret:+.1f}%</span></div>{spark}<dl><dt>市場全体（TOPIX）をずっと保有</dt><dd>{bench:+.1f}%</dd>"
            f"<dt>現金</dt><dd>{state['cash']:,.0f} 円</dd><dt>売買した回数・勝率</dt>"
            f"<dd>{len(state['trades'])}回・{rate}</dd><dt>次の営業日の注文予定</dt><dd>{pend}</dd></dl>"
            f"<table><tr><th>持っている銘柄</th><th>株数</th><th>買値</th><th>買った日</th></tr>{rows}</table>"
            f"<table><tr><th>最近売った銘柄</th><th>売った日</th><th>損益</th><th>理由</th></tr>{trades}</table></div>")


def build(rows_by_strategy, updated, years, state=None):
    parts = [f"<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>AIトレーダー</title><style>{CSS}</style></head><body><main>"
             f"<h1>AIトレーダー 今日のサイン</h1><div class='meta'>更新：{updated}"
             f"（直近の終値で判定）</div>", _paper(state)]
    for title, rows in rows_by_strategy:
        parts.append(f"<h2>{html.escape(title)}</h2><div class='grid'>")
        for r in rows:
            label, cls = SIGNAL_LABEL[r["signal"]]
            bt = r["bt"]
            parts.append(
                f"<div class='card'><div class='top'><div><div class='name'>{html.escape(r['name'])}</div>"
                f"<div class='code'>{r['code']}</div></div><span class='badge {cls}'>{label}</span></div>"
                f"<div class='price'>{r['price']:,.1f} 円</div>{_spark(r['close'])}"
                f"<dl><dt>過去{years}年の試運転</dt><dd>{_pct(bt['return_pct'])}</dd>"
                f"<dt>ずっと持っていたら</dt><dd>{_pct(bt['hold_pct'])}</dd>"
                f"<dt>売買回数・勝率</dt><dd>{bt['trades']}回・{_pct(bt['win_rate']).lstrip('+')}</dd></dl></div>")
        parts.append("</div>")
    parts.append("<p class='note'>これは投資判断の参考情報で、利益を保証するものではありません。"
                 "試運転の成績は手数料・税金を含みません。</p></main></body></html>")
    return "".join(parts)
