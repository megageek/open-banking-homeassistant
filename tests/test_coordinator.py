"""Tests for bank-connection coordinator updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.open_banking.const import CONF_REFRESH_INTERVAL, CONF_REQUISITION_ID
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator


async def test_coordinator_loads_accounts_and_balances(hass) -> None:
    """A linked requisition is expanded into account details and balances."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": ["account-1"]})
    client.async_get_account_details = AsyncMock(return_value={"account": {"currency": "GBP"}})
    client.async_get_account_balances = AsyncMock(
        return_value={
            "balances": [
                {
                    "balanceType": "interimAvailable",
                    "balanceAmount": {"amount": "12.34", "currency": "GBP"},
                }
            ]
        }
    )
    entry = MagicMock()
    subentry = MagicMock()
    subentry.subentry_id = "bank-1"
    subentry.data = {CONF_REQUISITION_ID: "req-1", CONF_REFRESH_INTERVAL: 240}
    coordinator = OpenBankingDataUpdateCoordinator(hass, entry, subentry, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["accounts"]["account-1"]["details"]["currency"] == "GBP"
    assert data["accounts"]["account-1"]["balances"][0]["balanceType"] == "interimAvailable"
