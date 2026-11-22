"""市場全体から候補銘柄を絞り込む（スクリーニング）。

対象：東証の規模区分で TOPIX Core30・Large70・Mid400（＝TOPIX500 相当の大型・中型株）。
銘柄一覧は日本取引所（JPX）が公開している「東証上場銘柄一覧」から毎回取得します。
"""
import numpy as np
import pandas as pd

JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"
SIZE_CLASSES = ["TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"]

# JPXの一覧が取れなかったときの予備（主な大型株）
FALLBACK = {
    "7203": "トヨタ自動車", "6758": "ソニーグループ", "8306": "三菱UFJフィナンシャル・グループ",
    "9432": "NTT", "7974": "任天堂", "9984": "ソフトバンクグループ", "6861": "キーエンス",
    "8035": "東京エレクトロン", "9983": "ファーストリテイリング", "6501": "日立製作所",
    "8316": "三井住友フィナンシャルグループ", "8411": "みずほフィナンシャルグループ",
    "4063": "信越化学工業", "6098": "リクルートホールディングス", "8058": "三菱商事",
    "8001": "伊藤忠商事", "8031": "三井物産", "4502": "武田薬品工業", "7267": "本田技研工業",
    "6902": "デンソー", "9433": "KDDI", "9434": "ソフトバンク", "6367": "ダイキン工業",
    "4568": "第一三共", "6954": "ファナック", "7741": "HOYA", "8766": "東京海上ホールディングス",
    "2914": "日本たばこ産業", "6981": "村田製作所", "4519": "中外製薬",
}


def universe():
    """{証券コード: 銘柄名} を返す。"""
    try:
        import re

        import requests
        page = requests.get(JPX_PAGE, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
        link = re.search(r'href="([^"]+data_j\.xls)"', page).group(1)
        url = link if link.startswith("http") else "https://www.jpx.co.jp" + link
        from io import BytesIO
        xls = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).content
        df = pd.read_excel(BytesIO(xls), dtype=str)
        df = df[df["規模区分"].isin(SIZE_CLASSES)]
        result = dict(zip(df["コード"].str.strip(), df["銘柄名"].str.strip()))
        if len(result) > 100:
            print(f"JPXの一覧から {len(result)} 銘柄を対象にします")
            return result
    except Exception as e:  # 取得失敗時は予備リスト
        print("JPXの一覧を取得できませんでした:", e)
    print(f"予備リストの {len(FALLBACK)} 銘柄を対象にします")
    return dict(FALLBACK)


def score(close, volume, rules):
    """各銘柄の指標を計算し、条件を満たすものに点数をつけて並べた表を返す。"""
    rows = []
    for code in close.columns:
        c, v = close[code].dropna(), volume[code].reindex(close[code].dropna().index)
        if len(c) < 260:
            continue
        price = c.iloc[-1]
        turnover = (c * v).tail(20).mean() / 1e8            # 1日の売買代金（億円）
        ma75 = c.rolling(75).mean()
        trend_up = price > ma75.iloc[-1] and ma75.iloc[-1] > ma75.iloc[-21]
        vol = c.pct_change().tail(250).std() * np.sqrt(250) * 100  # 年率の値動きの大きさ（%）
        mom = (price / c.iloc[-126] - 1) * 100              # 半年の上昇率（%）
        rows.append({"code": code, "price": price, "turnover": turnover,
                     "trend_up": trend_up, "volatility": vol, "momentum": mom,
                     "cost_100": price * 100})
    df = pd.DataFrame(rows)
    ok = (df["turnover"] >= rules["min_turnover_oku"]) \
        & (df["volatility"].between(rules["min_vol"], rules["max_vol"])) \
        & (df["cost_100"] <= rules["max_cost_100"])
    if rules.get("trend_only", True):
        ok &= df["trend_up"]
    df = df[ok].copy()
    # 半年の上昇率と売買代金の順位を足して点数にする（大きいほど良い）
    df["score"] = df["momentum"].rank(pct=True) * 0.6 + df["turnover"].rank(pct=True) * 0.4
    return df.sort_values("score", ascending=False).head(rules["top_n"])
