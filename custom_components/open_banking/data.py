"""Runtime types for the Open Banking integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import OpenBankingApiClient
    from .coordinator import OpenBankingDataUpdateCoordinator

type OpenBankingConfigEntry = ConfigEntry[OpenBankingData]


@dataclass
class OpenBankingData:
    """Runtime data stored on the parent config entry."""

    client: OpenBankingApiClient
    coordinators: dict[str, OpenBankingDataUpdateCoordinator]
