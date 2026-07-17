"""Tests for parent config-flow behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow

from custom_components.open_banking.api import OpenBankingAuthenticationError
from custom_components.open_banking.const import CONF_SECRET_ID, CONF_SECRET_KEY, DOMAIN


async def test_invalid_credentials(hass) -> None:
    """Rejected user secrets keep the flow open with an auth error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(
        "custom_components.open_banking.config_flow_handler.config_flow.OpenBankingApiClient.async_authenticate",
        AsyncMock(side_effect=OpenBankingAuthenticationError),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SECRET_ID: "invalid", CONF_SECRET_KEY: "invalid"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_valid_credentials_continue_to_first_bank(hass) -> None:
    """Valid user secrets continue directly to first-bank configuration."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(
        "custom_components.open_banking.config_flow_handler.config_flow.OpenBankingApiClient.async_authenticate",
        AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SECRET_ID: "valid-id", CONF_SECRET_KEY: "valid-key"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "connection"
