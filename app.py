import json
import logging
import os
import re
import html
import sqlite3
import time
from collections import defaultdict, deque
from threading import Lock, Thread
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, render_template, request
from groq import Groq

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
TELEGRAM_MAX_HISTORY = int(os.getenv("TELEGRAM_MAX_HISTORY", "10"))
TELEGRAM_RATE_LIMIT_COUNT = int(os.getenv("TELEGRAM_RATE_LIMIT_COUNT", "5"))
TELEGRAM_RATE_LIMIT_WINDOW = int(os.getenv("TELEGRAM_RATE_LIMIT_WINDOW", "60"))
TELEGRAM_MEMORY_DB_PATH = os.getenv("TELEGRAM_MEMORY_DB_PATH", "telegram_memory.db")
TELEGRAM_DAILY_QUOTA = int(os.getenv("TELEGRAM_DAILY_QUOTA", "0"))
APP_STARTED_AT = time.time()
runtime_config = {"model": DEFAULT_MODEL}

rate_limit_hits = defaultdict(deque)
stats_store = {
    "telegram_requests_total": 0,
    "telegram_errors_total": 0,
    "telegram_messages_total": 0,
    "telegram_unique_chats": set(),
}
store_lock = Lock()


def get_db_connection():
    conn = sqlite3.connect(TELEGRAM_MEMORY_DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_memory_store():
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telegram_chat_history_chat_id_id "
            "ON telegram_chat_history(chat_id, id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_quota_daily (
                chat_id TEXT NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY(chat_id, day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_allowlist_overrides (
                chat_id TEXT PRIMARY KEY,
                allowed INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )


init_memory_store()


def get_telegram_token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def get_webhook_secret():
    return os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


def get_webhook_header_secret():
    return os.getenv("TELEGRAM_WEBHOOK_HEADER_SECRET", "").strip()


def get_allowed_chat_ids():
    raw = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return None
    allowed = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            allowed.add(int(item))
        except ValueError:
            logger.warning("TELEGRAM_ALLOWED_CHAT_IDS mengandung nilai tidak valid: %s", item)
    return allowed if allowed else None


def get_admin_chat_ids():
    raw = os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "").strip()
    if not raw:
        return set()
    admins = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            admins.add(int(item))
        except ValueError:
            logger.warning("TELEGRAM_ADMIN_CHAT_IDS mengandung nilai tidak valid: %s", item)
    return admins


def get_runtime_model():
    with store_lock:
        return runtime_config["model"]


def set_runtime_model(model):
    with store_lock:
        runtime_config["model"] = model
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO bot_settings(key, value) VALUES ('current_model', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (model,),
        )


def load_runtime_model():
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = 'current_model'"
        ).fetchone()
    if row and row[0]:
        with store_lock:
            runtime_config["model"] = row[0]


def set_allow_override(chat_id, allowed):
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO telegram_allowlist_overrides(chat_id, allowed)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET allowed=excluded.allowed
            """,
            (str(chat_id), 1 if allowed else 0),
        )


def get_allow_override(chat_id):
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT allowed FROM telegram_allowlist_overrides WHERE chat_id = ?",
            (str(chat_id),),
        ).fetchone()
    if row is None:
        return None
    return bool(row[0])


def is_chat_allowed(chat_id):
    override = get_allow_override(chat_id)
    if override is not None:
        return override
    allowed_chat_ids = get_allowed_chat_ids()
    if allowed_chat_ids is None:
        return True
    return int(chat_id) in allowed_chat_ids


load_runtime_model()


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


def normalize_telegram_command(text):
    if not text:
        return ""
    cmd = text.strip().split()[0].lower()
    # Handle group format: /help@YourBot
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    return cmd


def is_rate_limited(chat_id):
    now = time.time()
    with store_lock:
        entries = rate_limit_hits[chat_id]
        while entries and (now - entries[0]) > TELEGRAM_RATE_LIMIT_WINDOW:
            entries.popleft()
        if len(entries) >= TELEGRAM_RATE_LIMIT_COUNT:
            return True
        entries.append(now)
        return False


def register_telegram_request(chat_id):
    with store_lock:
        stats_store["telegram_requests_total"] += 1
        stats_store["telegram_unique_chats"].add(chat_id)


def register_telegram_message():
    with store_lock:
        stats_store["telegram_messages_total"] += 1


def register_telegram_error():
    with store_lock:
        stats_store["telegram_errors_total"] += 1


def get_telegram_stats_summary():
    uptime_seconds = int(time.time() - APP_STARTED_AT)
    with store_lock:
        return (
            "Statistik Bot:\n"
            f"- Uptime: {uptime_seconds}s\n"
            f"- Total request webhook: {stats_store['telegram_requests_total']}\n"
            f"- Total pesan diproses: {stats_store['telegram_messages_total']}\n"
            f"- Total error: {stats_store['telegram_errors_total']}\n"
            f"- Total chat unik: {len(stats_store['telegram_unique_chats'])}\n"
            f"- Model aktif: {get_runtime_model()}"
        )


def check_and_increment_daily_quota(chat_id):
    if TELEGRAM_DAILY_QUOTA <= 0:
        return True, 0, 0

    day = time.strftime("%Y-%m-%d", time.gmtime())
    chat_key = str(chat_id)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT count FROM telegram_quota_daily WHERE chat_id = ? AND day = ?",
            (chat_key, day),
        ).fetchone()
        current = int(row[0]) if row else 0
        if current >= TELEGRAM_DAILY_QUOTA:
            return False, current, TELEGRAM_DAILY_QUOTA

        new_count = current + 1
        conn.execute(
            """
            INSERT INTO telegram_quota_daily(chat_id, day, count)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, day) DO UPDATE SET count=excluded.count
            """,
            (chat_key, day, new_count),
        )
    return True, new_count, TELEGRAM_DAILY_QUOTA


def reset_chat_history(chat_id):
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM telegram_chat_history WHERE chat_id = ?",
            (str(chat_id),),
        )


def build_messages_from_history(chat_id, user_text):
    max_messages = max(2, TELEGRAM_MAX_HISTORY * 2)
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM telegram_chat_history
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(chat_id), max_messages),
        ).fetchall()

    history = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return history + [{"role": "user", "content": user_text}]


def store_history_turn(chat_id, user_text, assistant_text):
    now = time.time()
    max_messages = max(2, TELEGRAM_MAX_HISTORY * 2)
    chat_key = str(chat_id)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO telegram_chat_history(chat_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
            """,
            (chat_key, user_text, now),
        )
        conn.execute(
            """
            INSERT INTO telegram_chat_history(chat_id, role, content, created_at)
            VALUES (?, 'assistant', ?, ?)
            """,
            (chat_key, assistant_text, now),
        )
        conn.execute(
            """
            DELETE FROM telegram_chat_history
            WHERE chat_id = ?
              AND id NOT IN (
                SELECT id
                FROM telegram_chat_history
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (chat_key, chat_key, max_messages),
        )


def chunk_telegram_text(text, chunk_size=4000):
    if text is None:
        text = ""
    text = str(text).strip()
    if not text:
        text = "..."
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def format_text_for_telegram(text):
    """Convert common markdown markers to Telegram HTML format."""
    if text is None:
        return ""

    output = html.escape(str(text))
    output = re.sub(r"```([\s\S]*?)```", lambda m: f"<pre>{m.group(1).strip()}</pre>", output)
    output = re.sub(r"`([^`]+)`", r"<code>\1</code>", output)
    output = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", output)
    output = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", output)
    output = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", output)
    output = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<i>\1</i>", output)
    output = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", output)
    output = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2">\1</a>',
        output,
    )
    return output.strip()


def plain_text_for_telegram(text):
    if text is None:
        return "..."
    output = str(text)
    output = re.sub(r"```([\s\S]*?)```", r"\1", output)
    output = re.sub(r"`([^`]+)`", r"\1", output)
    output = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", output)
    output = re.sub(r"__([^_\n]+)__", r"\1", output)
    output = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", output)
    output = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", output)
    output = re.sub(r"~~([^~\n]+)~~", r"\1", output)
    output = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1 (\2)", output)
    output = re.sub(r"<[^>]+>", "", output)
    output = html.unescape(output).strip()
    return output or "..."


def _send_telegram_payload(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=15):
        pass


def send_telegram_message(chat_id, text):
    token = get_telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diset di environment server.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    html_chunks = chunk_telegram_text(format_text_for_telegram(text))
    plain_chunks = chunk_telegram_text(plain_text_for_telegram(text))
    html_failed = False

    for chunk in html_chunks:
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
        try:
            _send_telegram_payload(url, payload)
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            logger.warning("Telegram HTML mode gagal (%s): %s", exc.code, error_body)
            if exc.code == 400:
                html_failed = True
                break
            raise

    if len(plain_chunks) == 0:
        return

    # Fallback plain text when HTML parsing fails on Telegram side.
    if html_failed:
        for chunk in plain_chunks:
            _send_telegram_payload(url, {"chat_id": chat_id, "text": chunk})


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify({"status": "ok"}), 200

@app.route('/debug/env', methods=['GET'])
def debug_env():
    allowed_chat_ids = get_allowed_chat_ids()
    admin_chat_ids = get_admin_chat_ids()
    return jsonify({
        "has_groq_api_key": bool(os.getenv("GROQ_API_KEY")),
        "has_telegram_bot_token": bool(get_telegram_token()),
        "has_telegram_webhook_secret": bool(get_webhook_secret()),
        "has_telegram_webhook_header_secret": bool(get_webhook_header_secret()),
        "telegram_allowed_chat_ids_count": 0 if allowed_chat_ids is None else len(allowed_chat_ids),
        "telegram_admin_chat_ids_count": len(admin_chat_ids),
        "telegram_daily_quota": TELEGRAM_DAILY_QUOTA,
        "groq_model": get_runtime_model(),
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
    expected_secret = get_webhook_secret()
    if not expected_secret:
        return jsonify({"error": "TELEGRAM_WEBHOOK_SECRET belum diset di environment server."}), 503
    if secret != expected_secret:
        return jsonify({"error": "Forbidden"}), 403
    expected_header_secret = get_webhook_header_secret()
    if expected_header_secret:
        actual_header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if actual_header_secret != expected_header_secret:
            return jsonify({"error": "Forbidden"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True, "ignored": "no_message"}), 200

    Thread(target=process_telegram_message, args=(message,), daemon=True).start()
    return jsonify({"ok": True, "accepted": True}), 200


def process_telegram_message(message):
    try:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        if not chat_id:
            return

        register_telegram_request(chat_id)
        admin_chat_ids = get_admin_chat_ids()
        is_admin = int(chat_id) in admin_chat_ids

        if not is_chat_allowed(chat_id):
            send_telegram_message(chat_id=chat_id, text="Maaf, chat ini belum diizinkan menggunakan bot.")
            return

        if text:
            register_telegram_message()

        cmd = normalize_telegram_command(text)
        if cmd in {"/help", "/start"}:
            reply_text = (
                "Halo! Kirim pertanyaanmu dan saya akan jawab.\n"
                "Perintah:\n"
                "/help - Tampilkan bantuan\n"
                "/reset - Hapus riwayat percakapan\n"
                "/stats - Lihat statistik bot\n"
                "/setmodel <model> - Ubah model (admin)\n"
                "/allow <chat_id> - Izinkan chat id (admin)\n"
                "/deny <chat_id> - Blok chat id (admin)"
            )
            send_telegram_message(chat_id=chat_id, text=reply_text)
            return

        if cmd == "/reset":
            reset_chat_history(chat_id)
            send_telegram_message(chat_id=chat_id, text="Riwayat percakapan sudah direset.")
            return

        if cmd == "/stats":
            send_telegram_message(chat_id=chat_id, text=get_telegram_stats_summary())
            return

        if cmd == "/setmodel":
            if not is_admin:
                send_telegram_message(chat_id=chat_id, text="Command ini hanya untuk admin.")
                return
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                send_telegram_message(chat_id=chat_id, text="Format: /setmodel <nama-model>")
                return
            new_model = parts[1].strip()
            set_runtime_model(new_model)
            send_telegram_message(chat_id=chat_id, text=f"Model aktif diganti ke: {new_model}")
            return

        if cmd in {"/allow", "/deny"}:
            if not is_admin:
                send_telegram_message(chat_id=chat_id, text="Command ini hanya untuk admin.")
                return
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                send_telegram_message(chat_id=chat_id, text=f"Format: {cmd} <chat_id>")
                return
            try:
                target_chat_id = int(parts[1].strip())
            except ValueError:
                send_telegram_message(chat_id=chat_id, text="chat_id harus berupa angka.")
                return
            set_allow_override(target_chat_id, allowed=(cmd == "/allow"))
            send_telegram_message(chat_id=chat_id, text=f"Override {cmd[1:]} berhasil untuk chat_id {target_chat_id}.")
            return

        if is_rate_limited(chat_id):
            send_telegram_message(chat_id=chat_id, text="Terlalu banyak request. Coba lagi beberapa saat.")
            return

        allowed_quota, usage, limit = check_and_increment_daily_quota(chat_id)
        if not allowed_quota:
            send_telegram_message(chat_id=chat_id, text=f"Kuota harian habis ({usage}/{limit}). Coba lagi besok.")
            return

        # Inform quickly so user knows request is being processed.
        send_telegram_message(chat_id=chat_id, text="Pesan diterima, sedang diproses...")

        if not text:
            reply_text = "Kirim pesan teks ya, nanti saya bantu jawab."
        else:
            try:
                messages = build_messages_from_history(chat_id, text)
                reply_text = generate_chat_response(messages=messages, model=get_runtime_model())
                store_history_turn(chat_id, text, reply_text)
            except Exception as exc:
                register_telegram_error()
                logger.exception("Error saat memproses request Telegram ke Groq")
                reply_text = f"Maaf, terjadi error saat memproses pesan: {exc}"

        send_telegram_message(chat_id=chat_id, text=reply_text)
    except (HTTPError, URLError, RuntimeError):
        register_telegram_error()
        logger.exception("Error saat memproses background Telegram message")
    except Exception:
        register_telegram_error()
        logger.exception("Unexpected error saat memproses background Telegram message")

if __name__ == '__main__':
    port = int(os.getenv("PORT", "8000"))
    app.run(debug=True, host='0.0.0.0', port=port)
