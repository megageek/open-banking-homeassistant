"""Bank connection status sensor."""

from __future__ import annotations

from custom_components.open_banking.const import (
    CONF_INSTITUTION_ID,
    CONF_INSTITUTION_NAME,
    DOMAIN,
    REQUISITION_STATUSES,
)
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from custom_components.open_banking.entity import OpenBankingEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo


class OpenBankingStatusSensor(OpenBankingEntity, SensorEntity):
    """Represent the requisition status without exposing sensitive metadata."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_options = REQUISITION_STATUSES
    _attr_translation_key = "connection_status"

    def __init__(self, coordinator: OpenBankingDataUpdateCoordinator) -> None:
        """Initialize the status sensor."""
        super().__init__(coordinator)
        subentry = coordinator.subentry
        institution_id = str(subentry.data[CONF_INSTITUTION_ID])
        self._attr_unique_id = f"{subentry.subentry_id}-status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=str(subentry.data.get(CONF_INSTITUTION_NAME, institution_id)),
            manufacturer="GoCardless",
            model=institution_id,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://bankaccountdata.gocardless.com/",
        )

    @property
    def native_value(self) -> str | None:
        """Return the requisition status code."""
        status = self.coordinator.data.get("requisition", {}).get("status")
        return str(status) if status else None
