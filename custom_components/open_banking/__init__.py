"""Open Banking integration for GoCardless Bank Account Data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import OpenBankingApiClient, OpenBankingAuthenticationError
from .callback import async_register_callback_view
from .const import CONF_SECRET_ID, CONF_SECRET_KEY, DOMAIN
from .coordinator import OpenBankingDataUpdateCoordinator
from .data import OpenBankingData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import OpenBankingConfigEntry

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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
    for subentry in entry.subentries.values():
        coordinator = OpenBankingDataUpdateCoordinator(hass, entry, subentry, client)
        coordinators[subentry.subentry_id] = coordinator
        await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenBankingConfigEntry) -> bool:
    """Unload the integration entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
