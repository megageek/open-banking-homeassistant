"""Tests for integration lifecycle setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.open_banking import async_setup, async_setup_entry, async_unload_entry
from custom_components.open_banking.api import OpenBankingAuthenticationError
from custom_components.open_banking.const import CONF_SECRET_ID, CONF_SECRET_KEY, DOMAIN
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed


async def test_setup_registers_callback_view(hass) -> None:
    """Integration setup registers the authorization callback endpoint."""
    with patch("custom_components.open_banking.async_register_callback_view") as register:
        assert await async_setup(hass, {}) is True

    register.assert_called_once_with(hass)


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


async def test_setup_entry_restores_and_persists_subentry_snapshot(hass) -> None:
    """Each subentry restores its own state and persists later coordinator updates."""

    class FakeStore:
        """Generic-compatible storage double."""

        created_with: tuple[object, int, str] | None = None
        saved: dict | None = None

        @classmethod
        def __class_getitem__(cls, item: object) -> type[FakeStore]:
            return cls

        def __init__(self, stored_hass: object, version: int, key: str) -> None:
            type(self).created_with = (stored_hass, version, key)

        async def async_load(self) -> dict:
            return {"bank-1": {"data": "restored"}}

        async def async_save(self, data: dict) -> None:
            type(self).saved = data

    entry = MagicMock()
    entry.entry_id = "entry-1"
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
        patch("custom_components.open_banking.OpenBankingDataUpdateCoordinator", return_value=coordinator) as create,
        patch("custom_components.open_banking.Store", FakeStore),
    ):
        await async_setup_entry(hass, entry)

    assert FakeStore.created_with == (hass, 1, f"{DOMAIN}.entry-1")
    coordinator.async_restore_snapshot.assert_called_once_with({"data": "restored"})
    save_snapshot = create.call_args.args[4]
    await save_snapshot({"data": "updated"})
    assert FakeStore.saved == {"bank-1": {"data": "updated"}}


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
