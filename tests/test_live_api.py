"""Opt-in tests against the live GoCardless Bank Account Data API."""

from __future__ import annotations

import os

from aiohttp import ClientSession
import pytest
import pytest_socket

from custom_components.open_banking.api import OpenBankingApiClient

pytestmark = pytest.mark.live_api


def _require_secret(name: str) -> str:
    """Return a live API secret or skip the test without exposing it."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not defined")
    return value


async def test_live_authentication_and_institutions() -> None:
    """Authenticate and perform a read-only request against the real API."""
    secret_id = _require_secret("OPEN_BANKING_SECRET_ID")
    secret_key = _require_secret("OPEN_BANKING_SECRET_KEY")
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["bankaccountdata.gocardless.com"])

    async with ClientSession() as session:
        client = OpenBankingApiClient(secret_id, secret_key, session)
        await client.async_authenticate()
        institutions = await client.async_get_institutions("GB")

    assert institutions
    assert all(isinstance(institution.get("id"), str) for institution in institutions)
