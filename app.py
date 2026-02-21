import json
import logging
import os
import re
import html
import hmac
import hashlib
import sqlite3
import time
from collections import defaultdict, deque
from threading import Lock, Thread
from urllib.parse import parse_qsl
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, render_template, request, has_request_context
from groq import Groq

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Kamu adalah asisten AI bernama SawiPresto. "
    "Saat ditanya nama, jawab bahwa namamu SawiPresto.",
)
TELEGRAM_MAX_HISTORY = int(os.getenv("TELEGRAM_MAX_HISTORY", "10"))
TELEGRAM_RATE_LIMIT_COUNT = int(os.getenv("TELEGRAM_RATE_LIMIT_COUNT", "5"))
TELEGRAM_RATE_LIMIT_WINDOW = int(os.getenv("TELEGRAM_RATE_LIMIT_WINDOW", "60"))
TELEGRAM_MEMORY_DB_PATH = os.getenv("TELEGRAM_MEMORY_DB_PATH", "telegram_memory.db")
TELEGRAM_DAILY_QUOTA = int(os.getenv("TELEGRAM_DAILY_QUOTA", "0"))
TELEGRAM_SEND_RETRY_COUNT = max(1, int(os.getenv("TELEGRAM_SEND_RETRY_COUNT", "3")))
TELEGRAM_SEND_RETRY_DELAY_SECONDS = float(
    os.getenv("TELEGRAM_SEND_RETRY_DELAY_SECONDS", "1.0")
)
TELEGRAM_PREMIUM_PRICE_XTR = max(1, int(os.getenv("TELEGRAM_PREMIUM_PRICE_XTR", "100")))
TELEGRAM_PREMIUM_DURATION_DAYS = max(1, int(os.getenv("TELEGRAM_PREMIUM_DURATION_DAYS", "30")))
TELEGRAM_PREMIUM_PLAN_NAME = os.getenv("TELEGRAM_PREMIUM_PLAN_NAME", "Premium 30 Hari").strip()
GAME_NAME = "SawiPresto Revenge"
GAME_ENERGY_REGEN_SECONDS = max(1, int(os.getenv("GAME_ENERGY_REGEN_SECONDS", "20")))
GAME_DEFAULT_MAX_ENERGY = max(5, int(os.getenv("GAME_DEFAULT_MAX_ENERGY", "20")))
GAME_DEFAULT_TAP_POWER = max(1, int(os.getenv("GAME_DEFAULT_TAP_POWER", "1")))
GAME_TAP_COOLDOWN_SECONDS = float(os.getenv("GAME_TAP_COOLDOWN_SECONDS", "0.35"))
GAME_MAX_TAP_BATCH = max(1, int(os.getenv("GAME_MAX_TAP_BATCH", "10")))
MINIAPP_SESSION_TTL_SECONDS = max(300, int(os.getenv("MINIAPP_SESSION_TTL_SECONDS", "86400")))
MINIAPP_SIGNING_SECRET = os.getenv("MINIAPP_SIGNING_SECRET", "").strip()
GAME_CHARACTER_BASE_ASSET = os.getenv(
    "GAME_CHARACTER_BASE_ASSET",
    "/static/game-assets/characters/sawipresto-base.png",
).strip()
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

GAME_SHOP_ITEMS = {
    "weapon_bamboo_spear": {
        "name": "Bamboo Spear",
        "type": "weapon",
        "price": 300,
        "tap_bonus": 2,
        "energy_bonus": 0,
        "asset": "/static/game-assets/weapons/bamboo-spear.png",
    },
    "weapon_shadow_blade": {
        "name": "Shadow Blade",
        "type": "weapon",
        "price": 1200,
        "tap_bonus": 6,
        "energy_bonus": 1,
        "asset": "/static/game-assets/weapons/shadow-blade.png",
    },
    "weapon_quantum_cleaver": {
        "name": "Quantum Cleaver",
        "type": "weapon",
        "price": 4500,
        "tap_bonus": 15,
        "energy_bonus": 2,
        "asset": "/static/game-assets/weapons/quantum-cleaver.png",
    },
    "pet_neko_drone": {
        "name": "Neko Drone",
        "type": "pet",
        "price": 800,
        "tap_bonus": 3,
        "energy_bonus": 0,
        "asset": "/static/game-assets/pets/neko-drone.png",
    },
    "pet_turbo_hammy": {
        "name": "Turbo Hammy",
        "type": "pet",
        "price": 2200,
        "tap_bonus": 8,
        "energy_bonus": 2,
        "asset": "/static/game-assets/pets/turbo-hammy.png",
    },
    "skin_ronin": {
        "name": "Ronin Jacket",
        "type": "skin",
        "price": 1500,
        "tap_bonus": 2,
        "energy_bonus": 3,
        "asset": "/static/game-assets/skins/ronin-jacket.png",
    },
}


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_subscriptions (
                chat_id TEXT PRIMARY KEY,
                plan_name TEXT NOT NULL,
                expires_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_game_state (
                chat_id TEXT PRIMARY KEY,
                coins INTEGER NOT NULL,
                energy INTEGER NOT NULL,
                max_energy INTEGER NOT NULL,
                tap_power INTEGER NOT NULL,
                level INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                weapon_id TEXT NOT NULL DEFAULT '',
                pet_id TEXT NOT NULL DEFAULT '',
                skin_id TEXT NOT NULL DEFAULT '',
                owned_items TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_game_sessions (
                token TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_game_idempotency (
                chat_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(chat_id, request_key)
            )
            """
        )


init_memory_store()


def ensure_column_exists(table_name, column_name, definition):
    with get_db_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row[1] for row in rows}
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


ensure_column_exists("telegram_game_state", "weapon_id", "weapon_id TEXT NOT NULL DEFAULT ''")
ensure_column_exists("telegram_game_state", "pet_id", "pet_id TEXT NOT NULL DEFAULT ''")
ensure_column_exists("telegram_game_state", "skin_id", "skin_id TEXT NOT NULL DEFAULT ''")
ensure_column_exists("telegram_game_state", "owned_items", "owned_items TEXT NOT NULL DEFAULT '[]'")


def get_telegram_token():
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def get_webhook_secret():
    return os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


def get_webhook_header_secret():
    return os.getenv("TELEGRAM_WEBHOOK_HEADER_SECRET", "").strip()


def get_app_base_url():
    explicit = os.getenv("APP_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    if has_request_context():
        return request.url_root.rstrip("/")
    return ""


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


def get_miniapp_signing_key():
    if MINIAPP_SIGNING_SECRET:
        return MINIAPP_SIGNING_SECRET.encode("utf-8")
    token = get_telegram_token()
    if not token:
        return b""
    return token.encode("utf-8")


def create_miniapp_session(chat_id):
    now = time.time()
    expires_at = now + MINIAPP_SESSION_TTL_SECONDS
    raw = f"{chat_id}:{now}:{os.urandom(16).hex()}"
    token = hmac.new(get_miniapp_signing_key(), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO telegram_game_sessions(token, chat_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, str(chat_id), expires_at, now),
        )
        conn.execute("DELETE FROM telegram_game_sessions WHERE expires_at < ?", (now,))
    return token, expires_at


def get_chat_id_from_session(token):
    if not token:
        return None
    now = time.time()
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT chat_id, expires_at
            FROM telegram_game_sessions
            WHERE token = ?
            """,
            (token,),
        ).fetchone()
    if not row:
        return None
    chat_id, expires_at = row
    if float(expires_at) < now:
        return None
    return int(chat_id)


def verify_telegram_webapp_init_data(init_data):
    token = get_telegram_token()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN belum diset.", None
    if not init_data:
        return False, "initData kosong.", None

    pairs = dict(parse_qsl(str(init_data), keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        return False, "hash tidak ditemukan di initData.", None

    data_check_string = "\n".join(
        f"{key}={pairs[key]}" for key in sorted(pairs.keys())
    )
    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return False, "initData tidak valid.", None

    auth_date = int(pairs.get("auth_date", "0") or "0")
    now = int(time.time())
    if auth_date <= 0 or (now - auth_date) > 86400:
        return False, "initData sudah kedaluwarsa.", None

    user_raw = pairs.get("user")
    if not user_raw:
        return False, "Data user tidak ditemukan.", None
    try:
        user_data = json.loads(user_raw)
    except Exception:
        return False, "Data user tidak valid.", None

    user_id = user_data.get("id")
    if not user_id:
        return False, "User id tidak ditemukan.", None
    return True, "", int(user_id)


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

    all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)
    try:
        chat_completion = groq_client.chat.completions.create(messages=all_messages, model=model)
        return chat_completion.choices[0].message.content
    except Exception as exc:
        # Auto-fallback when primary model is rate-limited.
        if exc.__class__.__name__ == "RateLimitError" and FALLBACK_MODEL and model != FALLBACK_MODEL:
            logger.warning("Model %s kena rate limit, fallback ke %s", model, FALLBACK_MODEL)
            chat_completion = groq_client.chat.completions.create(
                messages=all_messages,
                model=FALLBACK_MODEL,
            )
            return chat_completion.choices[0].message.content
        raise


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
        current_model = runtime_config["model"]
        return (
            "Statistik Bot:\n"
            f"- Uptime: {uptime_seconds}s\n"
            f"- Total request webhook: {stats_store['telegram_requests_total']}\n"
            f"- Total pesan diproses: {stats_store['telegram_messages_total']}\n"
            f"- Total error: {stats_store['telegram_errors_total']}\n"
            f"- Total chat unik: {len(stats_store['telegram_unique_chats'])}\n"
            f"- Model aktif: {current_model}"
        )


def get_subscription(chat_id):
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT plan_name, expires_at
            FROM telegram_subscriptions
            WHERE chat_id = ?
            """,
            (str(chat_id),),
        ).fetchone()
    if not row:
        return None
    return {"plan_name": row[0], "expires_at": float(row[1])}


def is_premium(chat_id):
    sub = get_subscription(chat_id)
    if not sub:
        return False
    return sub["expires_at"] > time.time()


def format_subscription_status(chat_id):
    sub = get_subscription(chat_id)
    if not sub:
        return "Plan saat ini: Free.\nGunakan /upgrade untuk aktifkan premium."
    expires_at = int(sub["expires_at"])
    if expires_at <= int(time.time()):
        return "Premium kamu sudah berakhir.\nGunakan /upgrade untuk perpanjang."
    expires_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(expires_at))
    return (
        f"Plan: {sub['plan_name']}\n"
        f"Status: Aktif\n"
        f"Berlaku sampai: {expires_utc}"
    )


def activate_premium(chat_id, plan_name=None, duration_days=None):
    if not plan_name:
        plan_name = TELEGRAM_PREMIUM_PLAN_NAME
    if not duration_days:
        duration_days = TELEGRAM_PREMIUM_DURATION_DAYS
    now = time.time()
    current = get_subscription(chat_id)
    base_time = now
    if current and current["expires_at"] > now:
        base_time = current["expires_at"]
    expires_at = base_time + (duration_days * 86400)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO telegram_subscriptions(chat_id, plan_name, expires_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                plan_name=excluded.plan_name,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
            """,
            (str(chat_id), plan_name, expires_at, now),
        )
    return expires_at


def _ensure_game_state(chat_id):
    now = time.time()
    chat_key = str(chat_id)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO telegram_game_state(
                chat_id, coins, energy, max_energy, tap_power, level, updated_at,
                weapon_id, pet_id, skin_id, owned_items
            )
            VALUES (?, 0, ?, ?, ?, 1, ?, '', '', '', '[]')
            ON CONFLICT(chat_id) DO NOTHING
            """,
            (
                chat_key,
                GAME_DEFAULT_MAX_ENERGY,
                GAME_DEFAULT_MAX_ENERGY,
                GAME_DEFAULT_TAP_POWER,
                now,
            ),
        )


def _load_game_state(chat_id):
    _ensure_game_state(chat_id)
    chat_key = str(chat_id)
    now = time.time()
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT coins, energy, max_energy, tap_power, level, updated_at, weapon_id, pet_id, skin_id, owned_items
            FROM telegram_game_state
            WHERE chat_id = ?
            """,
            (chat_key,),
        ).fetchone()
        if not row:
            return None

        coins, energy, max_energy, tap_power, level, updated_at, weapon_id, pet_id, skin_id, owned_items = row
        elapsed = max(0.0, now - float(updated_at))
        regen_units = int(elapsed // GAME_ENERGY_REGEN_SECONDS)
        if regen_units > 0 and int(energy) < int(max_energy):
            new_energy = min(int(max_energy), int(energy) + regen_units)
            remainder = elapsed % GAME_ENERGY_REGEN_SECONDS
            new_updated_at = now - remainder
            conn.execute(
                """
                UPDATE telegram_game_state
                SET energy = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (new_energy, new_updated_at, chat_key),
            )
            energy = new_energy
            updated_at = new_updated_at

    return {
        "chat_id": chat_key,
        "coins": int(coins),
        "energy": int(energy),
        "max_energy": int(max_energy),
        "tap_power": int(tap_power),
        "level": int(level),
        "weapon_id": weapon_id or "",
        "pet_id": pet_id or "",
        "skin_id": skin_id or "",
        "owned_items": _safe_owned_items(owned_items),
        "updated_at": float(updated_at),
    }


def _seconds_to_next_energy(state):
    if state["energy"] >= state["max_energy"]:
        return 0
    elapsed = max(0.0, time.time() - state["updated_at"])
    remain = GAME_ENERGY_REGEN_SECONDS - int(elapsed % GAME_ENERGY_REGEN_SECONDS)
    if remain == GAME_ENERGY_REGEN_SECONDS:
        return 0
    return max(1, remain)


def _safe_owned_items(raw):
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:
        pass
    return []


def _get_item(item_id):
    return GAME_SHOP_ITEMS.get(str(item_id))


def _calculate_equipment_bonus(state):
    total_tap_bonus = 0
    total_energy_bonus = 0
    for slot in ("weapon_id", "pet_id", "skin_id"):
        item = _get_item(state.get(slot, ""))
        if not item:
            continue
        total_tap_bonus += int(item.get("tap_bonus", 0))
        total_energy_bonus += int(item.get("energy_bonus", 0))
    return total_tap_bonus, total_energy_bonus


def _effective_tap_power(state):
    tap_bonus, _ = _calculate_equipment_bonus(state)
    return int(state["tap_power"]) + tap_bonus


def _effective_max_energy(state):
    _, energy_bonus = _calculate_equipment_bonus(state)
    return int(state["max_energy"]) + energy_bonus


def _decorate_game_state(state):
    if not state:
        return state
    owned_items = state.get("owned_items", [])
    equipment = {
        "weapon": _get_item(state.get("weapon_id", "")),
        "pet": _get_item(state.get("pet_id", "")),
        "skin": _get_item(state.get("skin_id", "")),
    }
    state["effective_tap_power"] = _effective_tap_power(state)
    state["effective_max_energy"] = _effective_max_energy(state)
    state["effective_energy"] = min(state["energy"], state["effective_max_energy"])
    state["equipment"] = equipment
    state["owned_items"] = [item for item in owned_items if item in GAME_SHOP_ITEMS]
    return state


def get_game_catalog():
    items = []
    for item_id, item in GAME_SHOP_ITEMS.items():
        record = {"id": item_id}
        record.update(item)
        items.append(record)
    return items


def _format_game_status(state):
    state = _decorate_game_state(state)
    next_energy = _seconds_to_next_energy(state)
    regen_line = "Energy penuh."
    if next_energy > 0:
        regen_line = f"+1 energy dalam {next_energy} detik."
    return (
        f"{GAME_NAME}\n"
        f"Level: {state['level']}\n"
        f"SawiCoin: {state['coins']}\n"
        f"Energy: {state['effective_energy']}/{state['effective_max_energy']} ({regen_line})\n"
        f"Tap Power: +{state['effective_tap_power']} coin / tap"
    )


def is_game_idempotency_replayed(chat_id, request_key):
    if not request_key:
        return False
    now = time.time()
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM telegram_game_idempotency
            WHERE chat_id = ? AND request_key = ?
            """,
            (str(chat_id), str(request_key)),
        ).fetchone()
        if row:
            return True
        conn.execute(
            """
            INSERT INTO telegram_game_idempotency(chat_id, request_key, created_at)
            VALUES (?, ?, ?)
            """,
            (str(chat_id), str(request_key), now),
        )
        conn.execute(
            "DELETE FROM telegram_game_idempotency WHERE created_at < ?",
            (now - 86400,),
        )
    return False


def game_tap(chat_id, tap_count=1):
    state = _load_game_state(chat_id)
    if not state:
        return False, None, 0
    tap_count = max(1, min(int(tap_count), GAME_MAX_TAP_BATCH))

    now = time.time()
    if (now - state["updated_at"]) < GAME_TAP_COOLDOWN_SECONDS:
        return False, state, 0

    effective_max_energy = _effective_max_energy(state)
    current_energy = min(state["energy"], effective_max_energy)
    if current_energy <= 0:
        return False, state, 0

    real_tap_count = min(tap_count, current_energy)
    gained = _effective_tap_power(state) * real_tap_count
    new_energy = max(0, current_energy - real_tap_count)
    new_coins = state["coins"] + gained
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE telegram_game_state
            SET coins = ?, energy = ?, updated_at = ?
            WHERE chat_id = ?
            """,
            (new_coins, new_energy, now, str(chat_id)),
        )
    updated = _load_game_state(chat_id)
    return True, updated, gained


def game_upgrade(chat_id):
    state = _load_game_state(chat_id)
    if not state:
        return False, None, 0
    cost = state["level"] * 50
    if state["coins"] < cost:
        return False, state, cost

    new_level = state["level"] + 1
    new_tap_power = state["tap_power"] + 1
    new_max_energy = state["max_energy"] + 2
    new_coins = state["coins"] - cost
    new_energy = min(state["energy"], new_max_energy)
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE telegram_game_state
            SET coins = ?, energy = ?, max_energy = ?, tap_power = ?, level = ?
            WHERE chat_id = ?
            """,
            (new_coins, new_energy, new_max_energy, new_tap_power, new_level, str(chat_id)),
        )
    return True, _load_game_state(chat_id), cost


def game_buy_item(chat_id, item_id):
    item = _get_item(item_id)
    if not item:
        return False, None, "Item tidak ditemukan."

    state = _load_game_state(chat_id)
    if not state:
        return False, None, "Gagal memuat state game."

    owned_items = set(state.get("owned_items", []))
    if item_id in owned_items:
        return False, _decorate_game_state(state), "Item sudah dimiliki."

    price = int(item["price"])
    if state["coins"] < price:
        return False, _decorate_game_state(state), f"Coin kurang. Butuh {price}."

    owned_items.add(item_id)
    slot_type = item["type"]
    weapon_id = state["weapon_id"]
    pet_id = state["pet_id"]
    skin_id = state["skin_id"]
    if slot_type == "weapon":
        weapon_id = item_id
    elif slot_type == "pet":
        pet_id = item_id
    elif slot_type == "skin":
        skin_id = item_id

    new_coins = state["coins"] - price
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE telegram_game_state
            SET coins = ?, weapon_id = ?, pet_id = ?, skin_id = ?, owned_items = ?
            WHERE chat_id = ?
            """,
            (
                new_coins,
                weapon_id,
                pet_id,
                skin_id,
                json.dumps(sorted(list(owned_items))),
                str(chat_id),
            ),
        )
    updated = _load_game_state(chat_id)
    return True, _decorate_game_state(updated), f"Berhasil membeli {item['name']}."


def game_leaderboard(limit=10):
    max_limit = max(1, min(int(limit), 20))
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, coins, level
            FROM telegram_game_state
            ORDER BY coins DESC, level DESC
            LIMIT ?
            """,
            (max_limit,),
        ).fetchall()

    if not rows:
        return "Leaderboard kosong. Jadilah pemain pertama!"

    lines = [f"Leaderboard {GAME_NAME}:"]
    rank = 1
    for row in rows:
        chat_id, coins, level = row
        lines.append(f"{rank}. chat {chat_id} - {int(coins)} coin (Lv {int(level)})")
        rank += 1
    return "\n".join(lines)


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


def _split_markdown_table_row(line):
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_table_separator(line):
    cells = _split_markdown_table_row(line)
    if not cells:
        return False
    for cell in cells:
        if not re.fullmatch(r":?-{3,}:?", cell):
            return False
    return True


def _render_markdown_table_block(table_lines):
    rows = []
    for line in table_lines:
        if _is_markdown_table_separator(line):
            continue
        rows.append(_split_markdown_table_row(line))

    if not rows:
        return "\n".join(table_lines)

    col_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (col_count - len(row)) for row in rows]
    widths = []
    for idx in range(col_count):
        widths.append(max(len(row[idx]) for row in normalized_rows))

    def fmt_row(row):
        cols = [row[idx].ljust(widths[idx]) for idx in range(col_count)]
        return "| " + " | ".join(cols) + " |"

    header = fmt_row(normalized_rows[0])
    separator = "| " + " | ".join("-" * w for w in widths) + " |"
    body = [fmt_row(row) for row in normalized_rows[1:]]
    table_text = "\n".join([header, separator] + body)
    return f"```\n{table_text}\n```"


def normalize_markdown_tables(text):
    if text is None:
        return ""
    lines = str(text).splitlines()
    if not lines:
        return str(text)

    output_lines = []
    i = 0
    total = len(lines)
    while i < total:
        if i + 1 < total and "|" in lines[i] and _is_markdown_table_separator(lines[i + 1]):
            table_block = [lines[i], lines[i + 1]]
            i += 2
            while i < total and lines[i].strip() and "|" in lines[i]:
                table_block.append(lines[i])
                i += 1
            output_lines.append(_render_markdown_table_block(table_block))
            continue

        output_lines.append(lines[i])
        i += 1

    return "\n".join(output_lines)


def format_text_for_telegram(text):
    """Convert common markdown markers to Telegram HTML format."""
    if text is None:
        return ""

    normalized = normalize_markdown_tables(text)
    source = str(normalized)
    protected = {}

    def protect_fenced_code(match):
        token = f"@@CODEBLOCK_{len(protected)}@@"
        protected[token] = f"<pre>{html.escape(match.group(1).strip())}</pre>"
        return token

    def protect_inline_code(match):
        token = f"@@INLINECODE_{len(protected)}@@"
        protected[token] = f"<code>{html.escape(match.group(1))}</code>"
        return token

    source = re.sub(r"```([\s\S]*?)```", protect_fenced_code, source)
    source = re.sub(r"`([^`]+)`", protect_inline_code, source)
    output = html.escape(source)
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
    for token, replacement in protected.items():
        output = output.replace(token, replacement)
    return output.strip()


def plain_text_for_telegram(text):
    if text is None:
        return "..."
    output = normalize_markdown_tables(text)
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
    last_exc = None
    for attempt in range(1, TELEGRAM_SEND_RETRY_COUNT + 1):
        try:
            with urllib_request.urlopen(req, timeout=15):
                return
        except HTTPError as exc:
            # Permanent errors (eg. bad payload/unauthorized) should fail fast.
            if exc.code < 500 and exc.code != 429:
                raise
            last_exc = exc
        except URLError as exc:
            last_exc = exc

        if attempt < TELEGRAM_SEND_RETRY_COUNT:
            delay = TELEGRAM_SEND_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Gagal kirim ke Telegram, retry %s/%s dalam %.1fs",
                attempt,
                TELEGRAM_SEND_RETRY_COUNT,
                delay,
            )
            time.sleep(delay)

    if last_exc:
        raise last_exc


def telegram_api_call(method, payload):
    token = get_telegram_token()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diset di environment server.")
    url = f"https://api.telegram.org/bot{token}/{method}"
    _send_telegram_payload(url, payload)


def send_telegram_message(chat_id, text, extra_payload=None):
    html_chunks = chunk_telegram_text(format_text_for_telegram(text))
    plain_chunks = chunk_telegram_text(plain_text_for_telegram(text))
    html_failed = False

    for chunk in html_chunks:
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
        if extra_payload:
            payload.update(extra_payload)
        try:
            telegram_api_call("sendMessage", payload)
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
            payload = {"chat_id": chat_id, "text": chunk}
            if extra_payload:
                payload.update(extra_payload)
            telegram_api_call("sendMessage", payload)


def send_telegram_stars_invoice(chat_id):
    payload = {
        "chat_id": chat_id,
        "title": TELEGRAM_PREMIUM_PLAN_NAME,
        "description": (
            f"Akses premium selama {TELEGRAM_PREMIUM_DURATION_DAYS} hari "
            "dengan prioritas layanan."
        ),
        "payload": f"premium:{TELEGRAM_PREMIUM_DURATION_DAYS}",
        "currency": "XTR",
        "prices": [
            {
                "label": TELEGRAM_PREMIUM_PLAN_NAME,
                "amount": TELEGRAM_PREMIUM_PRICE_XTR,
            }
        ],
    }
    telegram_api_call("sendInvoice", payload)


def answer_pre_checkout_query(pre_checkout_query_id, ok=True, error_message=None):
    payload = {"pre_checkout_query_id": pre_checkout_query_id, "ok": bool(ok)}
    if error_message:
        payload["error_message"] = error_message
    telegram_api_call("answerPreCheckoutQuery", payload)


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
        "telegram_premium_price_xtr": TELEGRAM_PREMIUM_PRICE_XTR,
        "telegram_premium_duration_days": TELEGRAM_PREMIUM_DURATION_DAYS,
        "game_name": GAME_NAME,
        "groq_model": get_runtime_model(),
    }), 200


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return ""
    return auth_header.split(" ", 1)[1].strip()


@app.route('/miniapp', methods=['GET'])
def miniapp():
    return render_template('miniapp.html', game_name=GAME_NAME)


@app.route('/api/game/auth', methods=['POST'])
def api_game_auth():
    payload = request.get_json(silent=True) or {}
    init_data = payload.get("initData", "")
    ok, error_message, user_id = verify_telegram_webapp_init_data(init_data)
    if not ok:
        return jsonify({"error": error_message}), 403
    if not is_chat_allowed(user_id):
        return jsonify({"error": "Chat belum diizinkan memakai game."}), 403

    token, expires_at = create_miniapp_session(user_id)
    state = _decorate_game_state(_load_game_state(user_id))
    return jsonify({
        "ok": True,
        "token": token,
        "expires_at": int(expires_at),
        "state": state,
        "config": {
            "game_name": GAME_NAME,
            "tap_cooldown_seconds": GAME_TAP_COOLDOWN_SECONDS,
            "max_tap_batch": GAME_MAX_TAP_BATCH,
            "energy_regen_seconds": GAME_ENERGY_REGEN_SECONDS,
            "character_base_asset": GAME_CHARACTER_BASE_ASSET,
        },
        "catalog": get_game_catalog(),
    }), 200


def _require_game_session():
    token = _extract_bearer_token()
    chat_id = get_chat_id_from_session(token)
    if not chat_id:
        return None, (jsonify({"error": "Session tidak valid atau kedaluwarsa."}), 401)
    return chat_id, None


@app.route('/api/game/state', methods=['GET'])
def api_game_state():
    chat_id, error = _require_game_session()
    if error:
        return error
    return jsonify({"ok": True, "state": _decorate_game_state(_load_game_state(chat_id))}), 200


@app.route('/api/game/tap', methods=['POST'])
def api_game_tap():
    chat_id, error = _require_game_session()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    tap_count = payload.get("tap_count", 1)
    request_key = request.headers.get("X-Idempotency-Key", "")
    if request_key and is_game_idempotency_replayed(chat_id, request_key):
        return jsonify({"ok": True, "replayed": True, "state": _decorate_game_state(_load_game_state(chat_id)), "gained": 0}), 200

    try:
        tap_count = int(tap_count)
    except (TypeError, ValueError):
        return jsonify({"error": "tap_count harus angka."}), 400

    ok, state, gained = game_tap(chat_id, tap_count=tap_count)
    if not state:
        return jsonify({"error": "Gagal memuat state game."}), 500
    return jsonify({
        "ok": True,
        "tapped": bool(ok),
        "gained": int(gained),
        "state": _decorate_game_state(state),
    }), 200


@app.route('/api/game/upgrade', methods=['POST'])
def api_game_upgrade():
    chat_id, error = _require_game_session()
    if error:
        return error
    request_key = request.headers.get("X-Idempotency-Key", "")
    if request_key and is_game_idempotency_replayed(chat_id, request_key):
        return jsonify({"ok": True, "replayed": True, "state": _decorate_game_state(_load_game_state(chat_id))}), 200

    ok, state, cost = game_upgrade(chat_id)
    if not state:
        return jsonify({"error": "Gagal memuat state game."}), 500
    return jsonify({
        "ok": True,
        "upgraded": bool(ok),
        "cost": int(cost),
        "state": _decorate_game_state(state),
    }), 200


@app.route('/api/game/buy', methods=['POST'])
def api_game_buy():
    chat_id, error = _require_game_session()
    if error:
        return error
    request_key = request.headers.get("X-Idempotency-Key", "")
    if request_key and is_game_idempotency_replayed(chat_id, request_key):
        return jsonify({"ok": True, "replayed": True, "state": _decorate_game_state(_load_game_state(chat_id))}), 200

    payload = request.get_json(silent=True) or {}
    item_id = str(payload.get("item_id", "")).strip()
    ok, state, message = game_buy_item(chat_id, item_id)
    if state is None:
        return jsonify({"error": message}), 500
    return jsonify({
        "ok": True,
        "bought": bool(ok),
        "message": message,
        "state": state,
        "catalog": get_game_catalog(),
    }), 200


@app.route('/api/game/leaderboard', methods=['GET'])
def api_game_leaderboard():
    chat_id, error = _require_game_session()
    if error:
        return error
    _ = chat_id
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, coins, level
            FROM telegram_game_state
            ORDER BY coins DESC, level DESC
            LIMIT 20
            """
        ).fetchall()
    data = [
        {"chat_id": str(row[0]), "coins": int(row[1]), "level": int(row[2])}
        for row in rows
    ]
    return jsonify({"ok": True, "leaderboard": data}), 200

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
    pre_checkout_query = update.get("pre_checkout_query")
    if pre_checkout_query:
        query_id = pre_checkout_query.get("id")
        if query_id:
            try:
                answer_pre_checkout_query(query_id, ok=True)
            except Exception:
                register_telegram_error()
                logger.exception("Error saat answerPreCheckoutQuery")
        return jsonify({"ok": True, "accepted": "pre_checkout"}), 200

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

        successful_payment = message.get("successful_payment") or {}
        if successful_payment:
            invoice_payload = str(successful_payment.get("invoice_payload") or "")
            duration_days = TELEGRAM_PREMIUM_DURATION_DAYS
            if invoice_payload.startswith("premium:"):
                try:
                    duration_days = max(1, int(invoice_payload.split(":", 1)[1]))
                except ValueError:
                    pass
            expires_at = activate_premium(
                chat_id=chat_id,
                plan_name=TELEGRAM_PREMIUM_PLAN_NAME,
                duration_days=duration_days,
            )
            expires_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(expires_at)))
            send_telegram_message(
                chat_id=chat_id,
                text=(
                    "Pembayaran berhasil. Premium aktif.\n"
                    f"Plan: {TELEGRAM_PREMIUM_PLAN_NAME}\n"
                    f"Berlaku sampai: {expires_utc}"
                ),
            )
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
                "/plan - Lihat status plan kamu\n"
                f"/upgrade - Upgrade ke {TELEGRAM_PREMIUM_PLAN_NAME} ({TELEGRAM_PREMIUM_PRICE_XTR} XTR)\n"
                f"/game - Buka {GAME_NAME} Mini App\n"
                "/play - Buka Mini App game\n"
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

        if cmd == "/plan":
            info = (
                f"{format_subscription_status(chat_id)}\n\n"
                f"Harga premium: {TELEGRAM_PREMIUM_PRICE_XTR} XTR / {TELEGRAM_PREMIUM_DURATION_DAYS} hari."
            )
            send_telegram_message(chat_id=chat_id, text=info)
            return

        if cmd == "/upgrade":
            try:
                send_telegram_stars_invoice(chat_id)
                send_telegram_message(
                    chat_id=chat_id,
                    text="Invoice premium sudah dikirim. Silakan lanjutkan pembayaran Telegram Stars.",
                )
            except Exception as exc:
                register_telegram_error()
                logger.exception("Error saat mengirim invoice Stars")
                send_telegram_message(
                    chat_id=chat_id,
                    text=f"Gagal membuat invoice premium: {exc}",
                )
            return

        if cmd == "/game":
            app_base_url = get_app_base_url()
            webapp_url = f"{app_base_url}/miniapp" if app_base_url else ""
            if not app_base_url:
                send_telegram_message(
                    chat_id=chat_id,
                    text=(
                        "Mini App belum aktif. Set environment APP_BASE_URL dulu, "
                        "contoh: https://namaservice.koyeb.app"
                    ),
                )
                return
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Play SawiPresto Revenge",
                            "web_app": {"url": webapp_url},
                        }
                    ]
                ]
            }
            reply = f"Buka {GAME_NAME} lewat Mini App:"
            send_telegram_message(
                chat_id=chat_id,
                text=reply,
                extra_payload={"reply_markup": keyboard},
            )
            return

        if cmd == "/play":
            app_base_url = get_app_base_url()
            webapp_url = f"{app_base_url}/miniapp" if app_base_url else ""
            if not app_base_url:
                send_telegram_message(
                    chat_id=chat_id,
                    text="Mini App belum aktif. Set APP_BASE_URL di environment server.",
                )
                return
            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "Play SawiPresto Revenge",
                            "web_app": {"url": webapp_url},
                        }
                    ]
                ]
            }
            send_telegram_message(
                chat_id=chat_id,
                text=f"Buka {GAME_NAME} lewat Mini App:",
                extra_payload={"reply_markup": keyboard},
            )
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

        if not is_premium(chat_id):
            allowed_quota, usage, limit = check_and_increment_daily_quota(chat_id)
            if not allowed_quota:
                send_telegram_message(chat_id=chat_id, text=f"Kuota harian habis ({usage}/{limit}). Coba lagi besok.")
                return

        if not text:
            reply_text = "Kirim pesan teks ya, nanti saya bantu jawab."
        else:
            try:
                messages = build_messages_from_history(chat_id, text)
                reply_text = generate_chat_response(messages=messages, model=get_runtime_model())
                store_history_turn(chat_id, text, reply_text)
            except Exception as exc:
                if exc.__class__.__name__ == "RateLimitError":
                    register_telegram_error()
                    wait_time = ""
                    match = re.search(r"try again in ([^.\n]+)", str(exc), flags=re.IGNORECASE)
                    if match:
                        wait_time = f" Coba lagi dalam {match.group(1).strip()}."
                    reply_text = (
                        "Layanan AI sedang mencapai batas kuota sementara."
                        f"{wait_time} Saya masih bisa lanjut setelah kuota tersedia."
                    )
                else:
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
