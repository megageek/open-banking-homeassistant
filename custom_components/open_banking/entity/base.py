"""Base entity for Open Banking entities."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..coordinator import OpenBankingDataUpdateCoordinator


class OpenBankingEntity(CoordinatorEntity[OpenBankingDataUpdateCoordinator]):
    """Common coordinator-backed Open Banking entity."""

    _attr_has_entity_name = True
