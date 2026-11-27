# Meme Coin News Scanner (alert-only)

Scans X recent search for meme-coin catalysts, deduplicates posts, scores them, and sends Telegram alerts. It does **not** execute trades.

## Setup

1. Install Python 3.10+.
2. Create an X Developer app and obtain an app Bearer Token with read access. Recent Search endpoint: `GET https://api.x.com/2/tweets/search/recent`.
3. Create a Telegram bot using `@BotFather`, send it a message, then find your chat ID (see below).
4. Copy `.env.example` to `.env`, add your credentials.
5. Install dependencies and run:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Telegram chat ID

After creating the bot and sending it `/start`, open:

`https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates`

Find `message.chat.id` in the JSON response and place that value in `TELEGRAM_CHAT_ID`.

## X API cost and polling

The scanner polls a few recent-search queries every 90 seconds by default. X API costs depend on returned posts and current pricing; set `MAX_RESULTS` lower and increase `POLL_SECONDS` to reduce usage. The API recent-search endpoint only searches the recent window (currently documented as the last 7 days).

## Configuration

- `MIN_ALERT_SCORE`: alert threshold (default 65)
- `POLL_SECONDS`: interval (default 90)
- `MAX_RESULTS`: 10–100 (default 25)
- `X_QUERIES`: custom queries separated by `||`

## Safety / signal quality

The score is a triage score, not a probability of a profitable trade. Verify source, ticker, token contract, liquidity, holders, and whether the token is actually related to the catalyst before trading. Social posts and AI summaries can be wrong or manipulated. Never put exchange private keys or wallet seed phrases in this project.

## Troubleshooting

- `401/403`: check X token and API access/credits.
- `429`: scanner backs off by sleeping; consider reducing queries or increasing interval.
- Telegram not sending: verify bot token, chat ID, and that you started the bot in a private chat.
- AI errors: scanner falls back to local heuristic scoring.
