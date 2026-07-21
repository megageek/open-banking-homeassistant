"""Transaction summary sensor."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from custom_components.open_banking.const import DOMAIN, TRANSACTION_STORAGE_DISABLED
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from custom_components.open_banking.coordinator.transactions import transaction_amount, transaction_date
from custom_components.open_banking.entity import OpenBankingEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

TRANSACTION_SUMMARY_KINDS = (
    "spending_today",
    "income_today",
    "spending_this_month",
    "income_this_month",
    "pending_outgoing",
    "pending_outgoing_today",
    "pending_outgoing_this_month",
)


class OpenBankingTransactionSummarySensor(OpenBankingEntity, SensorEntity):
    """Represent a derived account transaction total."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: OpenBankingDataUpdateCoordinator,
        account_id: str,
        kind: str,
        account: dict[str, Any],
        account_name: str,
        institution_identifier: tuple[str, str],
    ) -> None:
        """Initialize a transaction summary sensor."""
        super().__init__(coordinator)
        self._account_id = account_id
        self._kind = kind
        details = account.get("details", {})
        self._currency = str(details.get("currency") or "")
        self._attr_unique_id = f"{account_id}-transaction-{kind}"
        self._attr_translation_key = kind
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
            via_device=institution_identifier,
        )

    async def async_added_to_hass(self) -> None:
        """Schedule local-midnight summary rollover."""
        await super().async_added_to_hass()
        self._schedule_midnight()

    @property
    def available(self) -> bool:
        """Return whether transaction data is cached."""
        return (
            super().available
            and self.coordinator.transaction_mode != TRANSACTION_STORAGE_DISABLED
            and self._account_id in self.coordinator.transactions
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the account currency."""
        return self._currency or None

    @property
    def native_value(self) -> Decimal:
        """Return the derived transaction total."""
        cache = self.coordinator.transactions.get(self._account_id, {})
        today = dt_util.now().date()
        total = Decimal(0)
        is_pending = self._kind.startswith("pending_outgoing")
        status = "pending" if is_pending else "booked"
        for transaction in cache.get(status, []):
            if transaction.get("currency") != self._currency:
                continue
            amount = transaction_amount(transaction)
            item_date = transaction_date(transaction)
            if amount is None:
                continue
            if self._kind != "pending_outgoing" and (item_date is None or not self._includes_date(item_date, today)):
                continue
            if "spending" in self._kind or is_pending:
                if amount < 0:
                    total += -amount
            elif amount > 0:
                total += amount
        return total

    def _includes_date(self, item_date: Any, today: Any) -> bool:
        if self._kind.endswith("today"):
            return item_date == today
        if "this_month" in self._kind:
            return item_date.year == today.year and item_date.month == today.month
        return True

    def _schedule_midnight(self) -> None:
        next_midnight = dt_util.start_of_local_day(dt_util.now() + timedelta(days=1))

        @callback
        def async_midnight(_: Any) -> None:
            self.async_write_ha_state()
            self._schedule_midnight()

        self.async_on_remove(async_track_point_in_time(self.hass, async_midnight, next_midnight))
