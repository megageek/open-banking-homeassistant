"""Tests for integration lifecycle setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.open_banking import async_setup_entry, async_unload_entry
from custom_components.open_banking.api import OpenBankingAuthenticationError
from custom_components.open_banking.const import CONF_SECRET_ID, CONF_SECRET_KEY
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed


async def test_setup_entry_authenticates_refreshes_and_forwards_platforms(hass) -> None:
    """Entry setup authenticates, refreshes each subentry, and loads sensors."""
    entry = MagicMock()
    entry.data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    subentry = MagicMock(subentry_id="bank-1")
    entry.subentries = {"bank-1": subentry}
    client = MagicMock()
    client.async_authenticate = AsyncMock()
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with (
        patch("custom_components.open_banking.OpenBankingApiClient", return_value=client),
        patch("custom_components.open_banking.OpenBankingDataUpdateCoordinator", return_value=coordinator),
    ):
        assert await async_setup_entry(hass, entry) is True

    client.async_authenticate.assert_awaited_once()
    coordinator.async_config_entry_first_refresh.assert_awaited_once()
    assert entry.runtime_data.coordinators == {"bank-1": coordinator}
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(entry, [Platform.SENSOR])


async def test_setup_entry_converts_invalid_credentials_to_reauth(hass) -> None:
    """Credential rejection during setup triggers Home Assistant reauthentication."""
    entry = MagicMock()
    entry.data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    client = MagicMock()
    client.async_authenticate = AsyncMock(side_effect=OpenBankingAuthenticationError)

    with (
        patch("custom_components.open_banking.OpenBankingApiClient", return_value=client),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await async_setup_entry(hass, entry)


async def test_unload_entry_unloads_sensor_platform(hass) -> None:
    """Entry unload delegates all loaded platforms to Home Assistant."""
    entry = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(hass, entry) is True
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(entry, [Platform.SENSOR])
