"""Transaction update event entity."""

from __future__ import annotations

from typing import Any

from custom_components.open_banking.const import DOMAIN, TRANSACTION_STORAGE_DISABLED
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from custom_components.open_banking.entity import OpenBankingEntity
from homeassistant.components.event import EventEntity
from homeassistant.helpers.device_registry import DeviceInfo

EVENT_TRANSACTIONS_UPDATED = "transactions_updated"


class OpenBankingTransactionUpdateEvent(OpenBankingEntity, EventEntity):
    """Publish sanitized transaction cache changes for one account."""

    _attr_event_types = [EVENT_TRANSACTIONS_UPDATED]
    _attr_translation_key = "transaction_updates"

    def __init__(
        self,
        coordinator: OpenBankingDataUpdateCoordinator,
        account_id: str,
        account: dict[str, Any],
        account_name: str,
    ) -> None:
        """Initialize the transaction update event."""
        super().__init__(coordinator)
        self._account_id = account_id
        self._last_sequence = 0
        self._attr_unique_id = f"{account_id}-transaction-updates"
        details = account.get("details", {})
        identifier = next(
            (str(details[key]) for key in ("iban", "bban", "scan", "resourceId") if details.get(key)),
            account_id,
        )
        product = str(details.get("product") or details.get("cashAccountType") or "Bank account")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account_id)},
            name=account_name,
            manufacturer="GoCardless",
            model=f"{product} (•••• {identifier[-4:]})",
            via_device=(DOMAIN, coordinator.subentry.subentry_id),
        )

    @property
    def available(self) -> bool:
        """Return whether transaction support and the account are available."""
        return (
            super().available
            and self.coordinator.transaction_mode != TRANSACTION_STORAGE_DISABLED
            and self._account_id in self.coordinator.transactions
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe and publish a setup-time initial transaction update."""
        await super().async_added_to_hass()
        self._async_emit_latest_change()

    def _handle_coordinator_update(self) -> None:
        """Publish a new transaction change or update availability."""
        if not self._async_emit_latest_change():
            self.async_write_ha_state()

    def _async_emit_latest_change(self) -> bool:
        latest = self.coordinator.transaction_change_for_account(self._account_id)
        if latest is None:
            return False
        sequence, attributes = latest
        if sequence <= self._last_sequence:
            return False
        self._last_sequence = sequence
        self._trigger_event(EVENT_TRANSACTIONS_UPDATED, dict(attributes))
        self.async_write_ha_state()
        return True
