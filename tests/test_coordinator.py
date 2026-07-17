"""Tests for bank-connection coordinator updates."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.open_banking.api import (
    OpenBankingAuthenticationError,
    OpenBankingCommunicationError,
    OpenBankingRateLimitError,
)
from custom_components.open_banking.const import CONF_REFRESH_INTERVAL, CONF_REQUISITION_ID
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util


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


async def test_coordinator_does_not_load_unlinked_accounts(hass) -> None:
    """An incomplete requisition reports status without requesting account data."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "UA", "accounts": ["account-1"]})
    client.async_get_account_details = AsyncMock()
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data == {"requisition": {"status": "UA", "accounts": ["account-1"]}, "accounts": {}}
    client.async_get_account_details.assert_not_awaited()


async def test_coordinator_tracks_agreement_expiry_and_creates_warning(hass) -> None:
    """A linked agreement nearing expiry creates a fixable warning."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN", "accounts": [], "agreement": "agreement-1"})
    client.async_get_end_user_agreement = AsyncMock(
        return_value={
            "accepted": (dt_util.utcnow() - timedelta(days=84)).isoformat(),
            "access_valid_for_days": 90,
        }
    )
    coordinator = _coordinator(hass, client)

    await coordinator._async_update_data()  # noqa: SLF001

    issue = ir.async_get(hass).async_get_issue("open_banking", "requisition_expiry_bank-1")
    assert issue is not None
    assert issue.translation_key == "requisition_expiring"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert coordinator.requisition_expires_at is not None
    await coordinator.async_shutdown()


async def test_expired_requisition_stops_scheduling_and_creates_error(hass) -> None:
    """An expired requisition stops polling and raises an error repair."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "EX", "accounts": []})
    coordinator = _coordinator(hass, client)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data["requisition"]["status"] == "EX"
    assert coordinator._next_refresh_at is None  # noqa: SLF001
    issue = ir.async_get(hass).async_get_issue("open_banking", "requisition_expiry_bank-1")
    assert issue is not None
    assert issue.translation_key == "requisition_expired"
    assert issue.severity is ir.IssueSeverity.ERROR


def test_snapshot_for_previous_requisition_is_not_restored(hass) -> None:
    """Replacing a requisition invalidates its persisted coordinator snapshot."""
    coordinator = _coordinator(hass, MagicMock())

    coordinator.async_restore_snapshot(
        {
            "requisition_id": "old-requisition",
            "data": {"requisition": {"status": "LN"}, "accounts": {}},
        }
    )

    assert coordinator.data is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpenBankingAuthenticationError("expired"), ConfigEntryAuthFailed),
        (OpenBankingCommunicationError("offline"), UpdateFailed),
        (OpenBankingRateLimitError("wait", 30), UpdateFailed),
    ],
)
async def test_coordinator_normalizes_api_failures(hass, error: Exception, expected: type[Exception]) -> None:
    """API failures are translated into Home Assistant coordinator failures."""
    client = MagicMock()
    client.async_get_requisition = AsyncMock(side_effect=error)

    with pytest.raises(expected):
        await _coordinator(hass, client)._async_update_data()  # noqa: SLF001


def _coordinator(hass, client: MagicMock) -> OpenBankingDataUpdateCoordinator:
    """Create a coordinator with standard test configuration."""
    entry = MagicMock()
    entry.entry_id = "entry-1"
    subentry = MagicMock()
    subentry.subentry_id = "bank-1"
    subentry.title = "Example Bank"
    subentry.data = {CONF_REQUISITION_ID: "req-1", CONF_REFRESH_INTERVAL: 240}
    return OpenBankingDataUpdateCoordinator(hass, entry, subentry, client)
