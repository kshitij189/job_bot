# Senior Profile Finder Bot

Telegram webhook bot that returns up to five current, senior contacts for each requested company. It does **not** scrape LinkedIn or automate a LinkedIn account. Supply records only from a licensed/authorized people-data provider or your own permitted data.

## Setup

1. Revoke the Telegram token previously pasted into chat in **@BotFather**, then create a new one.
2. Copy `.env.example` to `.env` and fill in the new token, a random webhook secret, and your public HTTPS base URL. Keep `.env` private.
3. Copy `candidates.example.csv` to `candidates.csv` and replace the examples with authorized data. Required columns are `company,name,title,profile_url`; optional ones are `source,confidence,current`.
4. Create a virtual environment and install dependencies:

   ```powershell
   py -3.14 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

5. Deploy behind HTTPS (for example Render, Railway, Azure App Service, or a reverse proxy). Set the same environment variables in that platform—do not upload `.env`.
6. Register Telegram’s webhook once:

   ```powershell
   Invoke-RestMethod -Method POST `
     -Uri "$env:PUBLIC_BASE_URL/admin/set-webhook" `
     -Headers @{ Authorization = "Bearer $env:TELEGRAM_WEBHOOK_SECRET" }
   ```

## Usage

```text
/find Stripe
/find Atlassian | mnc
/find Stripe, Atlassian | mnc
```

When type is omitted, the bot defaults to `startup` roles. Use `| mnc` for multinationals. It ranks current employees by the role sets in `app.py`, removes duplicate people, and caps output at five records.

## Production notes

- Set `ALLOWED_TELEGRAM_USER_IDS` to your numeric Telegram user ID before a public deployment.
- Replace `load_candidates()` with an API client for your approved provider when available; preserve the `Candidate` fields and do not log profile data unnecessarily.
- The `/admin/set-webhook` endpoint is a convenience for initial registration. Remove or firewall it after setup.
- The app only receives Telegram messages through `/telegram/webhook`; Telegram validates requests with the configured secret header.
