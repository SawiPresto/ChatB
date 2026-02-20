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
   - `TELEGRAM_MAX_HISTORY` (opsional, default: `10`)
   - `TELEGRAM_RATE_LIMIT_COUNT` (opsional, default: `5`)
   - `TELEGRAM_RATE_LIMIT_WINDOW` (opsional, default: `60` detik)
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

Cek status webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

Perintah bot Telegram:

- `/help` atau `/start` -> bantuan
- `/reset` -> reset memori chat
- `/stats` -> statistik penggunaan bot
