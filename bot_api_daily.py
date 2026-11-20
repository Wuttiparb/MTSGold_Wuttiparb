"""Fetch and store daily BOT THB/USD weighted-average interbank rates."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = "https://gateway.api.bot.or.th/Stat-ReferenceRate/v2/DAILY_REF_RATE/"
PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
DATABASE_DIR = PROJECT_DIR / ".venv"
DATA_POINTS = 20
LOOKBACK_DAYS = 31
REQUEST_TIMEOUT_SECONDS = 30


def load_local_env(path: Path = ENV_FILE) -> None:
    """Load simple KEY=VALUE entries without overriding existing environment variables."""
    if not path.exists():
        return

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"{path}:{line_number}: invalid environment variable name")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def required_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} in .env before running the workflow.")
    return value


def get_nested_value(payload: object, path: str) -> object:
    value = payload
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"API response does not contain configured field path {path!r}.")
        value = value[key]
    return value


def normalize_records(payload: object) -> list[tuple[str, str, str]]:
    """Map API rows to ISO date, decimal rate, and original JSON."""
    records_path = os.environ.get("BOT_RECORDS_PATH", "result.data.data_detail").strip()
    date_field = os.environ.get("BOT_DATE_FIELD", "period").strip()
    rate_field = os.environ.get("BOT_RATE_FIELD", "rate").strip()
    rows = get_nested_value(payload, records_path)
    if isinstance(rows, dict) and isinstance(rows.get("data_detail"), list):
        rows = rows["data_detail"]
    if not isinstance(rows, list):
        if isinstance(rows, dict):
            shape = f"an object with keys: {', '.join(map(str, rows.keys()))}"
        else:
            shape = f"a {type(rows).__name__}"
        raise ValueError(
            f"API field path {records_path!r} resolved to {shape}, not a list. "
            "For this BOT response, set BOT_RECORDS_PATH=result.data.data_detail. "
            "A process environment variable overrides the value in .env; update or unset it."
        )

    normalized: list[tuple[str, str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"API record {index} is not an object.")
        if date_field not in row or rate_field not in row:
            raise ValueError(
                f"API record {index} lacks configured field {date_field!r} or {rate_field!r}; "
                "check the BOT portal and update the field mappings in .env."
            )
        try:
            day = date.fromisoformat(str(row[date_field])).isoformat()
            rate = Decimal(str(row[rate_field]))
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"API record {index} has an invalid date or rate.") from error
        if not rate.is_finite():
            raise ValueError(f"API record {index} has a non-finite rate.")
        normalized.append((day, str(rate), json.dumps(row, ensure_ascii=False, sort_keys=True)))

    return normalized


def period_parameter(setting_name: str, value: str, default_name: str) -> str:
    if not value:
        raise ValueError(f"{setting_name} cannot be blank.")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        return value
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{setting_name} must be a query parameter name (for example, "
            "'start_period'); the workflow calculates date values automatically."
        )
    print(
        f"Warning: {setting_name} contains a date, not a parameter name; "
        f"using {default_name!r}.",
        file=sys.stderr,
    )
    return default_name


def fetch_records(today: date | None = None) -> list[tuple[str, str, str]]:
    api_key = required_setting("BOT_API_KEY")
    header_name = os.environ.get("BOT_API_KEY_HEADER", "Authorization").strip()
    if not header_name:
        raise ValueError("BOT_API_KEY_HEADER cannot be blank.")
    start_param = period_parameter(
        "BOT_START_PERIOD_PARAM",
        os.environ.get("BOT_START_PERIOD_PARAM", "start_period").strip(),
        "start_period",
    )
    end_param = period_parameter(
        "BOT_END_PERIOD_PARAM",
        os.environ.get("BOT_END_PERIOD_PARAM", "end_period").strip(),
        "end_period",
    )

    end_day = (today or date.today()) - timedelta(days=1)
    start_day = end_day - timedelta(days=LOOKBACK_DAYS)
    query = urlencode({start_param: start_day.isoformat(), end_param: end_day.isoformat()})
    request = Request(
        f"{ENDPOINT}?{query}",
        headers={header_name: api_key, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            raise RuntimeError(
                "BOT API returned HTTP 401 Unauthorized. Verify BOT_API_KEY, "
                "BOT_API_KEY_HEADER, and that your portal account is subscribed to this API."
            ) from error
        if error.code == 404:
            raise RuntimeError(
                f"BOT API returned HTTP 404 for {error.url}. Verify the endpoint path and "
                "query parameter names."
            ) from error
        raise RuntimeError(f"BOT API request failed with HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach the BOT API: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("BOT API returned invalid JSON.") from error

    records = normalize_records(payload)
    return sorted(records, key=lambda record: record[0])[-DATA_POINTS:]


def database_path() -> Path:
    applicant_name = required_setting("APPLICANT_ENGLISH_NAME")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", applicant_name.strip()).strip("_")
    if not safe_name:
        raise ValueError("APPLICANT_ENGLISH_NAME must contain at least one English letter or digit.")
    return DATABASE_DIR / f"bot_api_daily_{safe_name}.db"


def append_records(path: Path, records: list[tuple[str, str, str]]) -> int:
    if not records:
        raise ValueError("The BOT API returned no data records.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_rates (
                day TEXT PRIMARY KEY,
                rate TEXT NOT NULL,
                source_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO exchange_rates (day, rate, source_json, fetched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                rate = excluded.rate,
                source_json = excluded.source_json,
                fetched_at = excluded.fetched_at
            """,
            [(day, rate, source_json, fetched_at) for day, rate, source_json in records],
        )
        connection.execute(
            """
            DELETE FROM exchange_rates
            WHERE day NOT IN (
                SELECT day FROM exchange_rates ORDER BY day DESC LIMIT ?
            )
            """,
            (DATA_POINTS,),
        )
        return connection.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0]


def main() -> int:
    load_local_env()
    path = database_path()
    records = fetch_records()
    count = append_records(path, records)
    print(f"Stored {len(records)} fetched record(s); database now has {count}: {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
