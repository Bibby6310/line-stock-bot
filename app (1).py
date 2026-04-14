"""
LINE Stock Bot - 台股查詢、到價通知、AI 問答、定時推播
"""

import os
import json
import threading
import time
import logging
from datetime import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    PushMessageRequest, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent,
    JoinEvent, FollowEvent
)
import requests
import schedule

# ============================================================
# 設定
# ============================================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

app = Flask(__name__)

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# 資料儲存
# ============================================================
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"groups": [], "alerts": [], "watchlist": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

bot_data = load_data()

# ============================================================
# 台股查詢
# ============================================================
def get_stock_price(stock_id: str) -> dict:
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        if "msgArray" in data and len(data["msgArray"]) > 0:
            info = data["msgArray"][0]
            return {
                "success": True,
                "name": info.get("n", stock_id),
                "code": stock_id,
                "price": float(info.get("z", 0)) if info.get("z", "-") != "-" else float(info.get("y", 0)),
                "yesterday": float(info.get("y", 0)),
                "open": info.get("o", "-"),
                "high": info.get("h", "-"),
                "low": info.get("l", "-"),
                "volume": info.get("v", "-"),
                "time": info.get("t", "-"),
            }

        url2 = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_{stock_id}.tw"
        resp2 = requests.get(url2, headers=headers, timeout=10)
        data2 = resp2.json()

        if "msgArray" in data2 and len(data2["msgArray"]) > 0:
            info = data2["msgArray"][0]
            return {
                "success": True,
                "name": info.get("n", stock_id),
                "code": stock_id,
                "price": float(info.get("z", 0)) if info.get("z", "-") != "-" else float(info.get("y", 0)),
                "yesterday": float(info.get("y", 0)),
                "open": info.get("o", "-"),
                "high": info.get("h", "-"),
                "low": info.get("l", "-"),
                "volume": info.get("v", "-"),
                "time": info.get("t", "-"),
            }

        return {"success": False, "error": f"找不到股票代碼 {stock_id}"}

    except Exception as e:
        logger.error(f"查詢股票失敗: {e}")
        return {"success": False, "error": str(e)}


def format_stock_info(info: dict) -> str:
    if not info["success"]:
        return f"❌ {info['error']}"

    price = info["price"]
    yesterday = info["yesterday"]
    change = price - yesterday
    change_pct = (change / yesterday * 100) if yesterday else 0

    if change > 0:
        arrow = "🔴 ▲"
    elif change < 0:
        arrow = "🟢 ▼"
    else:
        arrow = "⚪ ─"

    return (
        f"📊 {info['name']}（{info['code']}）\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 現價：{price:.2f}\n"
        f"{arrow} 漲跌：{change:+.2f}（{change_pct:+.2f}%）\n"
        f"📈 開盤：{info['open']}\n"
        f"🔺 最高：{info['high']}\n"
        f"🔻 最低：{info['low']}\n"
        f"📦 成交量：{info['volume']} 張\n"
        f"🕐 時間：{info['time']}"
    )


# ============================================================
# AI 問答
# ============================================================
def ask_ai(question: str) -> str:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    if OPENAI_API_KEY:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "你是一個股票投資助手，用繁體中文回答。回答簡潔，控制在 300 字以內。"},
                        {"role": "user", "content": question},
                    ],
                    "max_tokens": 500,
                },
                timeout=30,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"AI 問答失敗: {e}")
            return "🤖 AI 暫時無法回應，請稍後再試。"

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "system": "你是一個股票投資助手，用繁體中文回答。回答簡潔，控制在 300 字以內。",
                    "messages": [{"role": "user", "content": question}],
                },
                timeout=30,
            )
            data = resp.json()
            return data["content"][0]["text"]
        except Exception as e:
            logger.error(f"AI 問答失敗: {e}")
            return "🤖 AI 暫時無法回應，請稍後再試。"

    return "🤖 尚未設定 AI API Key，請聯繫管理員。"


# ============================================================
# 到價通知
# ============================================================
def add_alert(user_or_group_id: str, stock_id: str, target_price: float, direction: str):
    alert = {
        "target_id": user_or_group_id,
        "stock_id": stock_id,
        "target_price": target_price,
        "direction": direction,
        "created_at": datetime.now().isoformat(),
        "triggered": False,
    }
    bot_data["alerts"].append(alert)
    save_data(bot_data)
    return alert


def check_alerts():
    if not bot_data["alerts"]:
        return

    stock_ids = list(set(a["stock_id"] for a in bot_data["alerts"] if not a["triggered"]))

    for stock_id in stock_ids:
        info = get_stock_price(stock_id)
        if not info["success"]:
            continue

        price = info["price"]
        for alert in bot_data["alerts"]:
            if alert["stock_id"] != stock_id or alert["triggered"]:
                continue

            triggered = False
            if alert["direction"] == "above" and price >= alert["target_price"]:
                triggered = True
                msg = f"🔔 到價通知！\n{info['name']}（{stock_id}）\n現價 {price:.2f} 已達到 {alert['target_price']:.2f} 以上！"
            elif alert["direction"] == "below" and price <= alert["target_price"]:
                triggered = True
                msg = f"🔔 到價通知！\n{info['name']}（{stock_id}）\n現價 {price:.2f} 已跌破 {alert['target_price']:.2f}！"

            if triggered:
                alert["triggered"] = True
                send_push_message(alert["target_id"], msg)

    save_data(bot_data)


def send_push_message(target_id: str, text: str):
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        try:
            api.push_message(PushMessageRequest(
                to=target_id,
                messages=[TextMessage(text=text)]
            ))
        except Exception as e:
            logger.error(f"推播失敗: {e}")


# ============================================================
# 定時推播
# ============================================================
def daily_market_summary():
    hot_stocks = ["2330", "2317", "2454", "2603", "0050"]
    lines = ["📋 每日盤後摘要\n━━━━━━━━━━━━━━"]

    for sid in hot_stocks:
        info = get_stock_price(sid)
        if info["success"]:
            price = info["price"]
            change = price - info["yesterday"]
            pct = (change / info["yesterday"] * 100) if info["yesterday"] else 0
            arrow = "🔴" if change > 0 else ("🟢" if change < 0 else "⚪")
            lines.append(f"{arrow} {info['name']} {price:.2f} ({change:+.2f}, {pct:+.1f}%)")

    msg = "\n".join(lines)

    for group_id in bot_data.get("groups", []):
        send_push_message(group_id, msg)


# ============================================================
# 指令解析
# ============================================================
HELP_TEXT = """📖 指令說明
━━━━━━━━━━━━━━
📊 查股票：
  輸入股票代碼，例如：
  「2330」或「查 2330」

🔔 到價通知：
  「通知 2330 > 600」
  → 台積電漲到 600 通知
  「通知 2330 < 500」
  → 台積電跌到 500 通知

📋 查看通知：
  「我的通知」

🗑 刪除通知：
  「刪除通知」→ 清除全部

🤖 AI 問答：
  「問 台積電未來展望」
  「問 什麼是本益比」

📈 熱門股：
  「熱門」→ 查看熱門股行情

❓ 說明：
  「help」或「說明」"""


def parse_command(text: str, source_id: str) -> str:
    text = text.strip()

    if text.lower() in ["help", "說明", "指令", "幫助", "?"]:
        return HELP_TEXT

    if text.isdigit() and len(text) == 4:
        info = get_stock_price(text)
        return format_stock_info(info)

    if text.startswith("查 ") or text.startswith("查"):
        stock_id = text.replace("查 ", "").replace("查", "").strip()
        if stock_id.isdigit():
            info = get_stock_price(stock_id)
            return format_stock_info(info)

    if text.startswith("通知"):
        try:
            parts = text.replace("通知", "").strip().split()
            stock_id = parts[0]
            direction = "above" if ">" in parts[1] else "below"
            price_str = parts[1].replace(">", "").replace("<", "").strip()
            if not price_str:
                price_str = parts[2]
            target_price = float(price_str)

            add_alert(source_id, stock_id, target_price, direction)
            dir_text = "漲到" if direction == "above" else "跌到"
            info = get_stock_price(stock_id)
            name = info.get("name", stock_id) if info["success"] else stock_id
            return f"✅ 已設定到價通知\n{name}（{stock_id}）{dir_text} {target_price:.2f} 時通知你！"
        except Exception:
            return "❌ 格式錯誤\n範例：通知 2330 > 600\n或：通知 2330 < 500"

    if text in ["我的通知", "通知列表"]:
        alerts = [a for a in bot_data["alerts"]
                  if a["target_id"] == source_id and not a["triggered"]]
        if not alerts:
            return "📭 目前沒有設定任何到價通知"
        lines = ["🔔 你的到價通知：\n━━━━━━━━━━━━━━"]
        for i, a in enumerate(alerts, 1):
            dir_text = "漲到" if a["direction"] == "above" else "跌到"
            lines.append(f"{i}. {a['stock_id']} {dir_text} {a['target_price']:.2f}")
        return "\n".join(lines)

    if text in ["刪除通知", "清除通知"]:
        bot_data["alerts"] = [a for a in bot_data["alerts"] if a["target_id"] != source_id]
        save_data(bot_data)
        return "🗑 已清除所有到價通知"

    if text in ["熱門", "熱門股"]:
        hot = ["2330", "2317", "2454", "2603", "0050"]
        lines = ["🔥 熱門股即時行情\n━━━━━━━━━━━━━━"]
        for sid in hot:
            info = get_stock_price(sid)
            if info["success"]:
                price = info["price"]
                change = price - info["yesterday"]
                pct = (change / info["yesterday"] * 100) if info["yesterday"] else 0
                arrow = "🔴" if change > 0 else ("🟢" if change < 0 else "⚪")
                lines.append(f"{arrow} {info['name']} {price:.2f} ({change:+.2f}, {pct:+.1f}%)")
        return "\n".join(lines)

    if text.startswith("問 ") or text.startswith("問"):
        question = text.replace("問 ", "").replace("問", "").strip()
        if question:
            return "🤖 " + ask_ai(question)
        return "❌ 請輸入問題，例如：問 台積電未來展望"

    return ""


# ============================================================
# LINE Webhook
# ============================================================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"收到 Webhook: {body[:200]}")

    try:
        handler.handle(body, signature)
    except Exception as e:
        logger.error(f"Webhook 處理失敗: {e}")
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text

    if event.source.type == "group":
        source_id = event.source.group_id
    elif event.source.type == "room":
        source_id = event.source.room_id
    else:
        source_id = event.source.user_id

    reply = parse_command(text, source_id)

    if reply:
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            ))


@handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    if group_id not in bot_data["groups"]:
        bot_data["groups"].append(group_id)
        save_data(bot_data)

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="👋 大家好！我是股票小幫手\n\n輸入「說明」查看所有功能！")]
        ))


@handler.add(FollowEvent)
def handle_follow(event):
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="👋 你好！我是股票小幫手\n\n輸入「說明」查看所有功能！")]
        ))


# ============================================================
# 背景排程
# ============================================================
def run_scheduler():
    schedule.every(1).minutes.do(check_alerts)
    schedule.every().day.at("14:30").do(daily_market_summary)

    while True:
        schedule.run_pending()
        time.sleep(30)


# ============================================================
# 啟動
# ============================================================
if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("📡 排程啟動完成")

    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
