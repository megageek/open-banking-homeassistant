"""Base entity for Open Banking entities."""

from __future__ import annotations

from custom_components.open_banking.coordinator import OpenBankingDataUpdateCoordinator
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class OpenBankingEntity(CoordinatorEntity[OpenBankingDataUpdateCoordinator]):
    """Common coordinator-backed Open Banking entity."""

    _attr_has_entity_name = True
