# BOT daily exchange-rate workflow

Starter project for collecting the Bank of Thailand (BOT) Weighted-average Interbank Exchange Rate (THB/USD) and storing the latest 20 daily data points in SQLite.

## Requirements

- Python 3.10 or later
- [`uv`](https://docs.astral.sh/uv/) for the assignment's project workflow
- A BOT API account and credentials from the [BOT Exchange Rates portal](https://portal.api.bot.or.th/portal/catalogue-products/exchange-rates-1)

A successful run fetches live data and creates the applicant-named SQLite database under `.venv/`. Keep the API credential in the ignored local `.env`; do not commit it.

## Setup

1. Install `uv` if it is not already available.
2. In this folder, run `uv sync`.
3. Copy `.env.example` to `.env`.
4. Fill in `APPLICANT_ENGLISH_NAME` and `BOT_API_KEY` from your own BOT portal account.
5. Confirm the API query parameter names and response field paths shown in `.env` against your portal subscription. Use parameter names such as `start_period` and `end_period`; the script calculates their date values automatically. The provided request example uses the `Authorization` header.

Never commit `.env` or publish API credentials. `.env` and `.venv/` are excluded by `.gitignore`.
If the API returns HTTP 401, verify the key, authentication header, and that the key's portal account is subscribed to this API.

## Run

```sh
uv run python bot_api_daily.py
```

The script requests a 31-day window ending yesterday, keeps up to the latest 20 returned daily records, and stores them in `.venv/bot_api_daily_{applicant_English_name}.db`. Re-running updates an existing date instead of inserting a duplicate and retains at most 20 dates.

The response mapping defaults to `result.data.data_detail`, `period`, and `rate`. The parser also unwraps the BOT `data_detail` list if `BOT_RECORDS_PATH` points to its enclosing object. If the portal's response differs, update `BOT_RECORDS_PATH`, `BOT_DATE_FIELD`, or `BOT_RATE_FIELD` in `.env`. The date field must use ISO `YYYY-MM-DD` format.
Values already exported in the shell environment take precedence over `.env`.

## Tests

```sh
uv sync --extra test
uv run pytest
```
e, and MBTI type in the email.
- [x] Before publishing, verify `.env` and all API credentials are excluded from the repository. Never commit credentials.
