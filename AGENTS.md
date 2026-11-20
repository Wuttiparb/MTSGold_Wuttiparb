# Project instructions

- Use Python 3.10 or later and the `uv` project workflow.
- Set up dependencies with `uv sync`.
- Run the application with `uv run python bot_api_daily.py`.
- Run tests with `uv run --extra test python -m pytest`.
- Keep API credentials in the ignored local `.env` file. Never commit credentials.
- Do not claim API data was fetched unless a run succeeded with user-provided credentials.
- Keep the SQLite database under `.venv/`, as required by the assignment.
- Check the BOT portal's current API response fields before changing the field mappings in `.env`.
