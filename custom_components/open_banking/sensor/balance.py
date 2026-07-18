"""Balance sensor entity."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from custom_components.open_banking.const import DOMAIN, REQUISITION_LINKED
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from custom_components.open_banking.entity import OpenBankingEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo


class OpenBankingBalanceSensor(OpenBankingEntity, SensorEntity):
    """Represent one balance type for a bank account."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: OpenBankingDataUpdateCoordinator,
        account_id: str,
        balance_type: str,
        account: dict[str, Any],
        account_name: str,
        institution_identifier: tuple[str, str],
    ) -> None:
        """Initialize the balance sensor."""
        super().__init__(coordinator)
        self._account_id = account_id
        self._balance_type = balance_type
        details = account.get("details", {})
        self._attr_unique_id = f"{account_id}-{balance_type}"
        self._attr_translation_key = "balance"
        self._attr_translation_placeholders = {"balance_type": balance_type}
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

    @property
    def available(self) -> bool:
        """Return whether the connection remains linked and data is current."""
        return (
            super().available
            and self.coordinator.data.get("requisition", {}).get("status") == REQUISITION_LINKED
            and self._balance() is not None
        )

    @property
    def native_value(self) -> Decimal | None:
        """Return the current balance amount."""
        balance = self._balance()
        if balance is None:
            return None
        try:
            return Decimal(str(balance["balanceAmount"]["amount"]))
        except InvalidOperation, KeyError, TypeError:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the API-provided currency."""
        balance = self._balance()
        if balance is None:
            return None
        currency = balance.get("balanceAmount", {}).get("currency")
        return str(currency) if currency else None

    def _balance(self) -> dict[str, Any] | None:
        """Return this entity's balance payload."""
        account = self.coordinator.data.get("accounts", {}).get(self._account_id, {})
        return next(
            (balance for balance in account.get("balances", []) if balance.get("balanceType") == self._balance_type),
            None,
        )
