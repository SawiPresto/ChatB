# ChatB

Flask chatbot dengan Groq API.

## Local Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GROQ_API_KEY="isi-api-key-kamu"
python app.py
```

App berjalan di `http://localhost:8000`.

## Deploy ke Koyeb (via GitHub + Dockerfile)

Project ini sudah siap deploy menggunakan `Dockerfile`.

1. Push repo ke GitHub.
2. Di Koyeb: `Create Web Service` -> pilih repo GitHub ini.
3. Build method: `Dockerfile`.
4. Set environment variable:
   - `GROQ_API_KEY` (wajib)
   - `GROQ_MODEL` (opsional, default: `openai/gpt-oss-120b`)
   - `TELEGRAM_BOT_TOKEN` (opsional, untuk fitur bot Telegram)
   - `TELEGRAM_WEBHOOK_SECRET` (opsional, untuk webhook Telegram)
   - `TELEGRAM_ALLOWED_CHAT_IDS` (opsional, whitelist chat id dipisah koma, contoh: `12345,67890`)
   - `TELEGRAM_ADMIN_CHAT_IDS` (opsional, chat id admin dipisah koma, contoh: `12345`)
   - `TELEGRAM_MAX_HISTORY` (opsional, default: `10`)
   - `TELEGRAM_RATE_LIMIT_COUNT` (opsional, default: `5`)
   - `TELEGRAM_RATE_LIMIT_WINDOW` (opsional, default: `60` detik)
   - `TELEGRAM_DAILY_QUOTA` (opsional, default: `0` = nonaktif)
   - `TELEGRAM_MEMORY_DB_PATH` (opsional, default: `telegram_memory.db`)
   - `TELEGRAM_WEBHOOK_HEADER_SECRET` (opsional, validasi header webhook Telegram)
5. Port otomatis pakai `PORT` dari Koyeb.
6. Health check endpoint: `/healthz`.

## Production Command

Container menjalankan:

```bash
gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT:-8000} app:app
```

## Integrasi Telegram (opsi native Flask)

Setelah deploy dan env `TELEGRAM_BOT_TOKEN` + `TELEGRAM_WEBHOOK_SECRET` terisi, set webhook bot Telegram:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<domain-koyeb-kamu>/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>
```

Jika menggunakan `TELEGRAM_WEBHOOK_HEADER_SECRET`, set webhook dengan `secret_token`:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<domain-koyeb-kamu>/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>&secret_token=<TELEGRAM_WEBHOOK_HEADER_SECRET>
```

Cek status webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

Perintah bot Telegram:

- `/help` atau `/start` -> bantuan
- `/reset` -> reset memori chat
- `/stats` -> statistik penggunaan bot
- `/feedbackstats` -> statistik feedback 👍/👎 (admin)
- `/setmodel <model>` -> ganti model aktif (admin)
- `/allow <chat_id>` -> izinkan chat id (admin)
- `/deny <chat_id>` -> blok chat id (admin)

Catatan memori Telegram:

- Riwayat chat Telegram disimpan di SQLite (`TELEGRAM_MEMORY_DB_PATH`).
- Jika container di-restart/deploy ulang tanpa storage persisten, data bisa hilang.
- Setiap jawaban bot juga menyertakan tombol feedback `👍/👎` dan tersimpan ke SQLite.
