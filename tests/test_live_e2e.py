"""Browser-driven end-to-end test using GoCardless Sandbox Finance."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import re
from uuid import uuid4

from aiohttp import ClientSession
from playwright.async_api import Page, async_playwright
import pytest
import pytest_socket

from custom_components.open_banking.api import OpenBankingApiClient, OpenBankingCommunicationError

pytestmark = pytest.mark.live_e2e

API_HOST = "bankaccountdata.gocardless.com"
SANDBOX_INSTITUTION_ID = "SANDBOXFINANCE_SFIN0000"
TEST_REDIRECT_URL = "https://example.com/open-banking/callback"
LINKED_STATUS = "LN"


def _require_secret(name: str) -> str:
    """Return a live API secret or skip without exposing it."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not defined")
    return value


async def _complete_sandbox_authorization(page: Page, link: str) -> None:
    """Complete the hosted consent and Sandbox Finance authentication journey."""
    await page.goto(link, wait_until="domcontentloaded")

    consent_button = page.get_by_role(
        "button",
        name=re.compile(r"(agree|allow|confirm|continue|proceed)", re.IGNORECASE),
    ).first
    await consent_button.click()

    await page.get_by_role(
        "button",
        name=re.compile(r"(log ?in|sign ?in|confirm|continue|submit)", re.IGNORECASE),
    ).first.click()
    await page.wait_for_url(re.compile(r"sandboxfinance\.gocardless\.io/.*/consent/approve/"))
    await page.get_by_text("Approve", exact=True).click()

    await page.wait_for_url(f"{TEST_REDIRECT_URL}*", timeout=30_000)


async def _wait_for_linked_requisition(
    client: OpenBankingApiClient,
    requisition_id: str,
) -> dict[str, object]:
    """Poll until Sandbox Finance has linked accounts to the requisition."""
    for _attempt in range(15):
        requisition = await client.async_get_requisition(requisition_id)
        if requisition.get("status") == LINKED_STATUS:
            return requisition
        await asyncio.sleep(1)
    pytest.fail("Sandbox requisition did not reach linked status")


async def _wait_for_account_data(
    client: OpenBankingApiClient,
    account_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Wait for Sandbox Finance account details and balances to become ready."""
    for _attempt in range(15):
        try:
            details = await client.async_get_account_details(account_id)
            balances = await client.async_get_account_balances(account_id)
        except OpenBankingCommunicationError:
            await asyncio.sleep(1)
            continue
        return details, balances
    pytest.fail("Sandbox account data did not become ready")


async def test_live_sandbox_full_authorization_journey() -> None:
    """Link Sandbox Finance in a browser and retrieve its account data."""
    secret_id = _require_secret("OPEN_BANKING_SECRET_ID")
    secret_key = _require_secret("OPEN_BANKING_SECRET_KEY")
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts([API_HOST])

    requisition_id: str | None = None
    async with ClientSession() as session:
        client = OpenBankingApiClient(secret_id, secret_key, session)
        await client.async_authenticate()
        try:
            created = await client.async_create_requisition(
                SANDBOX_INSTITUTION_ID,
                TEST_REDIRECT_URL,
                f"open-banking-e2e-test-{uuid4()}",
            )
            requisition_id = created.get("id")
            link = created.get("link")
            assert isinstance(requisition_id, str)
            assert isinstance(link, str)

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page()
                try:
                    await _complete_sandbox_authorization(page, link)
                except Exception:
                    artifact = Path(".ai-scratch/live-e2e-failure.png")
                    artifact.parent.mkdir(exist_ok=True)
                    await page.screenshot(path=artifact, full_page=True)
                    raise
                finally:
                    await browser.close()

            requisition = await _wait_for_linked_requisition(client, requisition_id)
            agreement_id = requisition.get("agreement") or requisition.get("agreements")
            assert isinstance(agreement_id, str)
            agreement = await client.async_get_end_user_agreement(agreement_id)
            accepted_value = agreement.get("accepted")
            assert isinstance(accepted_value, str)
            accepted = datetime.fromisoformat(accepted_value)
            valid_days = int(agreement["access_valid_for_days"])
            assert accepted <= datetime.now(UTC)
            assert accepted + timedelta(days=valid_days) > datetime.now(UTC)

            accounts = requisition.get("accounts")
            assert isinstance(accounts, list)
            assert accounts

            for account_id in accounts:
                assert isinstance(account_id, str)
                details, balances = await _wait_for_account_data(client, account_id)
                assert isinstance(details.get("account"), dict)
                assert isinstance(balances.get("balances"), list)
                for scope in ("details", "balances"):
                    quota = client.account_rate_limits[(account_id, scope)]
                    assert quota.limit > 0
                    assert 0 <= quota.remaining < quota.limit
                    assert quota.reset_after > 0
        finally:
            if requisition_id is not None:
                await client.async_delete_requisition(requisition_id)
