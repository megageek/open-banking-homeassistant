"""Next scheduled bank refresh timestamp sensor."""

from __future__ import annotations

from datetime import datetime

from custom_components.open_banking.const import DOMAIN
from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from custom_components.open_banking.entity import OpenBankingEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo


class OpenBankingNextRefreshSensor(OpenBankingEntity, SensorEntity):
    """Represent when bank data is next scheduled to refresh."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "next_refresh"

    def __init__(self, coordinator: OpenBankingDataUpdateCoordinator) -> None:
        """Initialize the timestamp sensor."""
        super().__init__(coordinator)
        subentry_id = coordinator.subentry.subentry_id
        self._attr_unique_id = f"{subentry_id}-next-refresh"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, subentry_id)})

    @property
    def native_value(self) -> datetime | None:
        """Return the next scheduled refresh timestamp."""
        return self.coordinator.next_refresh_at
