"""Open Banking integration for GoCardless Bank Account Data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.storage import Store

from .api import OpenBankingApiClient, OpenBankingAuthenticationError
from .callback import async_register_callback_view
from .const import (
    CONF_REFRESH_INTERVAL,
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    DEFAULT_REFRESH_WINDOW_END,
    DEFAULT_REFRESH_WINDOW_START,
    DEFAULT_REFRESHES_PER_DAY,
    DOMAIN,
    REQUISITION_EXPIRY_ISSUE_PREFIX,
)
from .coordinator import OpenBankingDataUpdateCoordinator
from .data import OpenBankingData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import OpenBankingConfigEntry

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
STORAGE_VERSION = 1


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration and authorization callback."""
    async_register_callback_view(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OpenBankingConfigEntry) -> bool:
    """Set up a GoCardless account and all institution subentries."""
    client = OpenBankingApiClient(
        str(entry.data[CONF_SECRET_ID]),
        str(entry.data[CONF_SECRET_KEY]),
        async_get_clientsession(hass),
    )
    try:
        await client.async_authenticate()
    except OpenBankingAuthenticationError as err:
        raise ConfigEntryAuthFailed from err

    coordinators: dict[str, OpenBankingDataUpdateCoordinator] = {}
    entry.runtime_data = OpenBankingData(client=client, coordinators=coordinators)
    store = Store[dict](hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    snapshots = await store.async_load() or {}
    stale_subentry_ids = set(snapshots) - set(entry.subentries)
    if stale_subentry_ids:
        for subentry_id in stale_subentry_ids:
            snapshots.pop(subentry_id, None)
            ir.async_delete_issue(hass, DOMAIN, f"{REQUISITION_EXPIRY_ISSUE_PREFIX}_{subentry_id}")
        await store.async_save(snapshots)
    for subentry in entry.subentries.values():

        async def async_save_snapshot(snapshot: dict, subentry_id: str = subentry.subentry_id) -> None:
            snapshots[subentry_id] = snapshot
            await store.async_save(snapshots)

        coordinator = OpenBankingDataUpdateCoordinator(hass, entry, subentry, client, async_save_snapshot)
        coordinators[subentry.subentry_id] = coordinator
        coordinator.async_restore_snapshot(snapshots.get(subentry.subentry_id))
        await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenBankingConfigEntry) -> bool:
    """Unload the integration entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        for subentry_id, coordinator in entry.runtime_data.coordinators.items():
            await coordinator.async_shutdown()
            ir.async_delete_issue(hass, DOMAIN, f"{REQUISITION_EXPIRY_ISSUE_PREFIX}_{subentry_id}")
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: OpenBankingConfigEntry) -> bool:
    """Migrate legacy bank-connection settings."""
    if entry.version != 1:
        return False
    if entry.minor_version >= 2:
        return True

    for subentry in entry.subentries.values():
        if CONF_REFRESH_INTERVAL not in subentry.data:
            continue
        data = dict(subentry.data)
        data.pop(CONF_REFRESH_INTERVAL, None)
        data.setdefault(CONF_REFRESHES_PER_DAY, DEFAULT_REFRESHES_PER_DAY)
        data.setdefault(CONF_REFRESH_WINDOW_START, DEFAULT_REFRESH_WINDOW_START)
        data.setdefault(CONF_REFRESH_WINDOW_END, DEFAULT_REFRESH_WINDOW_END)
        hass.config_entries.async_update_subentry(entry, subentry, data=data)

    hass.config_entries.async_update_entry(entry, minor_version=2)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: OpenBankingConfigEntry) -> None:
    """Reload after a parent or bank-connection update."""
    await hass.config_entries.async_reload(entry.entry_id)
