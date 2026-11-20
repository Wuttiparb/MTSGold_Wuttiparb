import json
import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
import sys
from urllib.error import HTTPError
from unittest.mock import MagicMock, Mock

import pytest

path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(path))

from bot_api_daily import append_records, fetch_records, load_local_env, normalize_records


def test_normalizes_configured_rows_and_preserves_source_json():
    payload = {
        "result": {
            "data": {
                "data_detail": [
                    {"period": "2026-11-18", "rate": "34.25", "currency": "USD"},
                ]
            }
        }
    }

    records = normalize_records(payload)

    assert records[0][:2] == ("2026-11-18", "34.25")
    assert json.loads(records[0][2])["currency"] == "USD"


def test_unwraps_bot_detail_list_when_path_points_to_wrapper(monkeypatch):
    payload = {
        "result": {
            "data": {
                "data_header": {"title": "not included in output"},
                "data_detail": [{"period": "2026-11-18", "rate": "34.25"}],
            }
        }
    }
    monkeypatch.setenv("BOT_RECORDS_PATH", "result.data")

    records = normalize_records(payload)

    assert records[0][:2] == ("2026-11-18", "34.25")


def test_reports_mismatched_record_fields():
    with pytest.raises(ValueError, match="check the BOT portal"):
        normalize_records(
            {"result": {"data": {"data_detail": [{"date": "2026-11-18"}]}}}
        )


def test_append_keeps_only_latest_twenty_days_without_duplicates(tmp_path: Path):
    path = tmp_path / "rates.db"
    records = [(f"2026-10-{day:02}", "34.5", "{}") for day in range(1, 21)]
    append_records(path, records)
    append_records(path, [("2026-10-20", "34.6", '{"updated": true}')])

    with closing(sqlite3.connect(path)) as connection, connection:
        rows = connection.execute(
            "SELECT day, rate FROM exchange_rates ORDER BY day"
        ).fetchall()

    assert len(rows) == 20
    assert rows[-1] == ("2026-10-20", "34.6")


def test_loads_local_env_without_overriding_existing_environment(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BOT_API_KEY='sample value'\nBOT_DATE_FIELD=period\n", encoding="utf-8"
    )
    monkeypatch.delenv("BOT_API_KEY", raising=False)
    monkeypatch.setenv("BOT_DATE_FIELD", "custom_date")

    load_local_env(env_path)

    assert os.environ["BOT_API_KEY"] == "sample value"
    assert os.environ["BOT_DATE_FIELD"] == "custom_date"


def test_sends_key_in_authorization_header_and_requests_expected_dates(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(
        {"result": {"data": {"data_detail": [
            {"period": "2026-11-19", "rate": "34.25"}
        ]}}}
    ).encode()
    settings = {
        "BOT_API_KEY": "dummy-test-key",
        "BOT_API_KEY_HEADER": "Authorization",
        "BOT_START_PERIOD_PARAM": "start_period",
        "BOT_END_PERIOD_PARAM": "end_period",
        "BOT_RECORDS_PATH": "result.data.data_detail",
        "BOT_DATE_FIELD": "period",
        "BOT_RATE_FIELD": "rate",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    urlopen = Mock(return_value=response)
    monkeypatch.setattr("bot_api_daily.urlopen", urlopen)

    fetch_records(today=date(2026, 11, 20))

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") == "dummy-test-key"
    assert "start_period=2026-10-19" in request.full_url
    assert "end_period=2026-11-19" in request.full_url


def test_unauthorized_response_gives_safe_configuration_guidance(monkeypatch):
    monkeypatch.setenv("BOT_API_KEY", "dummy-test-key")
    monkeypatch.setenv("BOT_API_KEY_HEADER", "Authorization")
    monkeypatch.setattr(
        "bot_api_daily.urlopen",
        Mock(side_effect=HTTPError("https://example.test", 401, "Unauthorized", None, None)),
    )

    with pytest.raises(RuntimeError, match="Verify BOT_API_KEY, BOT_API_KEY_HEADER"):
        fetch_records(today=date(2026, 11, 20))


def test_recovers_when_stale_environment_contains_date_values(monkeypatch, capsys):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps(
        {"result": {"data": {"data_detail": [
            {"period": "2026-11-19", "rate": "34.25"}
        ]}}}
    ).encode()
    monkeypatch.setenv("BOT_API_KEY", "dummy-test-key")
    monkeypatch.setenv("BOT_START_PERIOD_PARAM", "2026-10-19")
    monkeypatch.setenv("BOT_END_PERIOD_PARAM", "2026-11-19")
    urlopen = Mock(return_value=response)
    monkeypatch.setattr("bot_api_daily.urlopen", urlopen)

    fetch_records(today=date(2026, 11, 20))

    request = urlopen.call_args.args[0]
    assert "start_period=2026-10-19" in request.full_url
    assert "end_period=2026-11-19" in request.full_url
    assert "using 'start_period'" in capsys.readouterr().err


def test_not_found_error_identifies_url_without_credentials(monkeypatch):
    request_url = (
        "https://gateway.api.bot.or.th/Stat-ReferenceRate/v2/DAILY_REF_RATE/"
        "?start_period=2026-10-19&end_period=2026-11-19"
    )
    error = HTTPError(request_url, 404, "Not Found", None, None)
    monkeypatch.setenv("BOT_API_KEY", "dummy-test-key")
    monkeypatch.setattr("bot_api_daily.urlopen", Mock(side_effect=error))

    with pytest.raises(RuntimeError, match="HTTP 404 for https://gateway.api.bot.or.th"):
        fetch_records(today=date(2026, 11, 20))
