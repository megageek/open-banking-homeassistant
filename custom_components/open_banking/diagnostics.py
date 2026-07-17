"""Diagnostics support for Open Banking."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_ACCOUNT_HOLDER, CONF_REFERENCE, CONF_REQUISITION_ID, CONF_SECRET_ID, CONF_SECRET_KEY
from .data import OpenBankingConfigEntry

TO_REDACT = {
    CONF_ACCOUNT_HOLDER,
    CONF_REFERENCE,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    "accounts",
    "iban",
    "bban",
    "ownerName",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: OpenBankingConfigEntry,
) -> dict[str, Any]:
    """Return redacted entry and coordinator diagnostics."""
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "subentries": {key: dict(value.data) for key, value in entry.subentries.items()},
            "coordinators": {
                key: {
                    **coordinator.data,
                    "requisition_expires_at": (
                        coordinator.requisition_expires_at.isoformat() if coordinator.requisition_expires_at else None
                    ),
                }
                for key, coordinator in entry.runtime_data.coordinators.items()
            },
        },
        TO_REDACT,
    )
