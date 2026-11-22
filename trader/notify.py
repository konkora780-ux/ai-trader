"""LINE通知（LINE Messaging API の broadcast＝友だち全員への送信）。

自分だけが友だちのLINE公式アカウントを作れば、自分専用の通知になります。
"""
import os

import requests

URL = "https://api.line.me/v2/bot/message/broadcast"


def send_line(text):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("（LINEの鍵が未設定のため、送らずに表示だけします）\n" + text)
        return False
    res = requests.post(URL, timeout=30,
                        headers={"Authorization": f"Bearer {token}"},
                        json={"messages": [{"type": "text", "text": text[:4900]}]})
    if res.status_code != 200:
        print("LINE送信に失敗:", res.status_code, res.text)
        return False
    print("LINEに送信しました")
    return True
