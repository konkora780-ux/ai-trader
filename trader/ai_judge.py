"""AI（Claude）による買いの最終判断。

ルールで「買い」サインが出た銘柄について、プロのスイングトレーダーとして
チャート・地合い・出来高・ニュース・決算予定を確認し「買う／見送る」を決めます。
ANTHROPIC_API_KEY が無い、または月の上限を超えた場合は判断せず、ルールどおりにします。
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from trader.strategies import rsi_values

MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT, PRICE_SEARCH = 4.0, 20.0, 0.01  # ドル（100万トークンあたり／検索1回あたり）
USD_JPY = 155  # 費用の見積もり用（実際の請求はドル建て）
JST = timezone(timedelta(hours=9))

SYSTEM = """あなたは日本株のスイングトレード（数日〜数週間の保有）を専門とする経験豊富なプロのトレーダーです。
売買ルール（RSIの売られすぎ）で「買い」サインが出た銘柄について、翌営業日の寄付で実際に買うかを最終判断します。
これは練習用の仮想売買で、実際の注文は出ません。

判断の観点：
- チャート：上昇トレンド中の押し目か、下落トレンドの途中（落ちるナイフ）か。移動平均との位置関係。
- 地合い：市場全体（TOPIX）の流れ。
- 出来高：売られすぎの日に投げ売り（出来高急増）が出て一巡したか。
- ニュースと決算：web検索で直近のニュース、悪材料（不祥事・業績下方修正など）、次の決算発表日を確認する。
  決算発表が5営業日以内なら、値動きが読めないため原則見送る。
- リスク：損切りは買値から10%下で自動的に行われる前提。

迷う場合は見送ってください（資金を守ることを優先）。
最後の行に、次の形のJSONだけを書いてください（他の文字は付けない）：
{"decision": "buy" または "skip", "confidence": 1〜5の整数, "reason": "こんちゃんに伝える理由（日本語60字以内）"}"""


def _usage_path(root):
    return root / "docs" / "ai_usage.json"


def month_cost(root):
    p = _usage_path(root)
    month = datetime.now(JST).strftime("%Y-%m")
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get(month, 0.0)
    return 0.0


def _add_cost(root, yen):
    p = _usage_path(root)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    month = datetime.now(JST).strftime("%Y-%m")
    data[month] = round(data.get(month, 0.0) + yen, 1)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _facts(code, name, close, volume, market):
    c = close.dropna()
    r = rsi_values(c).iloc[-1]
    ma25, ma75 = c.rolling(25).mean().iloc[-1], c.rolling(75).mean().iloc[-1]
    v = volume.reindex(c.index) if volume is not None else None
    vol_ratio = (v.iloc[-1] / v.tail(20).mean()) if v is not None and v.tail(20).mean() else float("nan")
    m = market.dropna()
    m75 = m.rolling(75).mean().iloc[-1]
    recent = ", ".join(f"{x:.0f}" for x in c.tail(30))
    return (f"銘柄：{name}（証券コード {code}、東証）\n"
            f"日付：{c.index[-1].date()}　終値：{c.iloc[-1]:,.1f}円\n"
            f"RSI(14)：{r:.1f}　25日平均：{ma25:,.1f}円　75日平均：{ma75:,.1f}円\n"
            f"20日前比：{(c.iloc[-1] / c.iloc[-21] - 1) * 100:+.1f}%　半年前比：{(c.iloc[-1] / c.iloc[-126] - 1) * 100:+.1f}%\n"
            f"今日の出来高は20日平均の {vol_ratio:.2f} 倍\n"
            f"市場全体（TOPIX連動ETF）：75日平均より{'上' if m.iloc[-1] > m75 else '下'}"
            f"（20日前比 {(m.iloc[-1] / m.iloc[-21] - 1) * 100:+.1f}%）\n"
            f"直近30営業日の終値（古い順）：{recent}")


def judge(root, code, name, close, volume, market, cfg):
    """{"decision","confidence","reason","cost_yen"} を返す。判断しなかった場合は None。"""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    if month_cost(root) >= cfg["monthly_budget_yen"]:
        print("今月のAI利用料の上限に達したため、ルールどおりにします")
        return None
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": _facts(code, name, close, volume, market)
                 + "\n\nweb検索でニュースと決算予定を確認してから判断してください。"}]
    cost = 0.0
    try:
        for _ in range(4):
            res = client.beta.messages.create(
                model=MODEL, max_tokens=16000, system=SYSTEM, messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": cfg["max_searches"], "user_location": {"type": "approximate", "country": "JP"}}],
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            u = res.usage
            tokens_in = (u.input_tokens + (u.cache_creation_input_tokens or 0)
                         + (u.cache_read_input_tokens or 0))
            searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
            cost += (tokens_in * PRICE_IN + u.output_tokens * PRICE_OUT) / 1e6 + searches * PRICE_SEARCH
            if res.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": res.content})
                continue
            break
    except anthropic.APIError as e:
        print("AI判断でエラーが起きたため、ルールどおりにします:", e)
        _add_cost(root, cost * USD_JPY)
        return None
    yen = cost * USD_JPY
    _add_cost(root, yen)
    if res.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in res.content if b.type == "text")
    found = re.findall(r"\{[^{}]*\"decision\"[^{}]*\}", text)
    if not found:
        print("AIの返答を読み取れなかったため、見送りにします")
        return {"decision": "skip", "confidence": 0, "reason": "AIの返答を読み取れなかったため見送り", "cost_yen": yen}
    out = json.loads(found[-1])
    out["cost_yen"] = yen
    return out
