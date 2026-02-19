import logging
import os
import json
from urllib import request as urllib_request
from urllib.error import URLError, HTTPError

from flask import Flask, jsonify, render_template, request
from groq import Groq

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")


def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)


def generate_chat_response(messages, model=DEFAULT_MODEL):
    groq_client = get_groq_client()
    if groq_client is None:
        raise RuntimeError("GROQ_API_KEY belum diset di environment server.")

    chat_completion = groq_client.chat.completions.create(messages=messages, model=model)
    return chat_completion.choices[0].message.content

def send_telegram_message(chat_id, text):
        if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diset di environment server.")

        # Pastikan text tidak None
        if not text:
        text = "..."

        # Batas Telegram 4096 karakter
        text = str(text)
        if len(text) > 4000:
        text = text[:4000]

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

         payload = {
             "chat_id": chat_id,
             "text": text,
                   }

         body = json.dumps(payload).encode("utf-8")

         req = urllib_request.Request(
         url,
           Data=body,
           headers={"Content-Type": "application/json"},
           method="POST",
                                )

         with urllib_request.urlopen(req, timeout=15) as response:
              return response.read()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify({"status": "ok"}), 200

@app.route('/debug/env', methods=['GET'])
def debug_env():
    return jsonify({
        "has_groq_api_key": bool(os.getenv("GROQ_API_KEY")),
        "groq_model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
    }), 200

@app.route('/chat', methods=['POST'])
def process_chat():
    data = request.get_json(silent=True) or {}
    messages = data.get('messages', [])
    model = data.get('model', DEFAULT_MODEL)

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "Payload tidak valid. 'messages' harus berupa list dan tidak boleh kosong."}), 400

    try:
        response = generate_chat_response(messages=messages, model=model)
        return jsonify({"response": response})
    except Exception as exc:
        logger.exception("Error saat memproses request ke Groq")
        return jsonify({"error": f"Gagal memproses chat: {exc}"}), 502


@app.route('/telegram/webhook/<secret>', methods=['POST'])
def telegram_webhook(secret):
    if not TELEGRAM_WEBHOOK_SECRET:
        return jsonify({"error": "TELEGRAM_WEBHOOK_SECRET belum diset di environment server."}), 503
    if secret != TELEGRAM_WEBHOOK_SECRET:
        return jsonify({"error": "Forbidden"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True, "ignored": "no_message"}), 200

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id:
        return jsonify({"ok": True, "ignored": "no_chat_id"}), 200

    if not text:
        reply_text = "Kirim pesan teks ya, nanti saya bantu jawab."
    elif text.lower() in {"/start", "/help"}:
        reply_text = "Halo! Kirim pertanyaanmu, nanti saya jawab."
    else:
        try:
            reply_text = generate_chat_response(
                messages=[{"role": "user", "content": text}],
                model=DEFAULT_MODEL,
            )
        except Exception as exc:
            logger.exception("Error saat memproses request Telegram ke Groq")
            reply_text = f"Maaf, terjadi error saat memproses pesan: {exc}"

    try:
        send_telegram_message(chat_id=chat_id, text=reply_text)
        return jsonify({"ok": True}), 200
    except (HTTPError, URLError, RuntimeError) as exc:
        logger.exception("Error saat mengirim balasan ke Telegram")
            return jsonify({"ok": False}), 200

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8000"))
    app.run(debug=True, host='0.0.0.0', port=port)
