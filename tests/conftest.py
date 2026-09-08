"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
from unittest.mock import MagicMock, patch

import pytest


# Tests must never reach a real database. `cli.main` calls load_dotenv() at
# import time (override=False), so pre-seeding an empty DATABASE_URL here
# blocks .env from injecting the production Supabase URL into the process.
# `create_storage_engine()` treats an empty value as "use in-memory SQLite".
os.environ["DATABASE_URL"] = ""
os.environ.setdefault("TRADINGAGENTS_STORAGE_ENABLED", "false")


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "DART_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "KRX_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))
    # Re-assert per test in case a test or import mutated it.
    monkeypatch.setenv("DATABASE_URL", "")


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
