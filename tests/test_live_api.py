"""Opt-in tests against the live GoCardless Bank Account Data API."""

from __future__ import annotations

import os
from uuid import uuid4

from aiohttp import ClientSession
import pytest
import pytest_socket

from custom_components.open_banking.api import OpenBankingApiClient
from custom_components.open_banking.const import SANDBOX_INSTITUTION_ID

pytestmark = pytest.mark.live_api

TEST_REDIRECT_URL = "https://example.com/open-banking/callback"


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


async def test_live_sandbox_requisition_lifecycle() -> None:
    """Create, retrieve, and clean up a Sandbox Finance requisition."""
    secret_id = _require_secret("OPEN_BANKING_SECRET_ID")
    secret_key = _require_secret("OPEN_BANKING_SECRET_KEY")
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(["bankaccountdata.gocardless.com"])

    requisition_id: str | None = None
    async with ClientSession() as session:
        client = OpenBankingApiClient(secret_id, secret_key, session)
        await client.async_authenticate()
        try:
            created = await client.async_create_requisition(
                SANDBOX_INSTITUTION_ID,
                TEST_REDIRECT_URL,
                f"open-banking-live-test-{uuid4()}",
            )
            requisition_id = created.get("id")

            assert isinstance(requisition_id, str)
            assert created["institution_id"] == SANDBOX_INSTITUTION_ID
            assert created["status"] == "CR"
            assert isinstance(created.get("link"), str)
            agreement_id = created.get("agreement") or created.get("agreements")
            assert isinstance(agreement_id, str)

            agreement = await client.async_get_end_user_agreement(agreement_id)
            assert agreement["id"] == agreement_id
            assert int(agreement["access_valid_for_days"]) > 0
            assert agreement["institution_id"] == SANDBOX_INSTITUTION_ID

            retrieved = await client.async_get_requisition(requisition_id)

            assert retrieved["id"] == requisition_id
            assert retrieved["institution_id"] == SANDBOX_INSTITUTION_ID
            assert retrieved["status"] == "CR"
            assert retrieved["accounts"] == []
            assert (retrieved.get("agreement") or retrieved.get("agreements")) == agreement_id
        finally:
            if requisition_id is not None:
                await client.async_delete_requisition(requisition_id)
