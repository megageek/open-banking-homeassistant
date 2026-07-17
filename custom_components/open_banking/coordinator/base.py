"""Data coordinator for one bank connection subentry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from custom_components.open_banking.api import (
    OpenBankingApiClient,
    OpenBankingApiError,
    OpenBankingAuthenticationError,
    OpenBankingRateLimitError,
)
from custom_components.open_banking.const import (
    CONF_REFRESH_INTERVAL,
    CONF_REQUISITION_ID,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    LOGGER,
    REQUISITION_LINKED,
)
from custom_components.open_banking.data import OpenBankingConfigEntry
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed


class OpenBankingDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch requisition, account metadata, and balances for a subentry."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: OpenBankingConfigEntry,
        subentry: ConfigSubentry,
        client: OpenBankingApiClient,
    ) -> None:
        """Initialize the coordinator."""
        self.subentry = subentry
        self.client = client
        interval = int(subentry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL))
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}-{subentry.subentry_id}",
            update_interval=timedelta(minutes=interval),
            always_update=False,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all data for this bank connection."""
        try:
            requisition = await self.client.async_get_requisition(str(self.subentry.data[CONF_REQUISITION_ID]))
            accounts: dict[str, dict[str, Any]] = {}
            if requisition.get("status") == REQUISITION_LINKED:
                for account_id in requisition.get("accounts", []):
                    details_response = await self.client.async_get_account_details(account_id)
                    balances_response = await self.client.async_get_account_balances(account_id)
                    accounts[account_id] = {
                        "details": details_response.get("account", {}),
                        "balances": balances_response.get("balances", []),
                    }
        except OpenBankingAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except OpenBankingRateLimitError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=err.retry_after,
            ) from err
        except UpdateFailed:
            raise
        except OpenBankingApiError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err
        else:
            return {"requisition": requisition, "accounts": accounts}
