"""Tests for parent config-flow behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.open_banking.api import OpenBankingAuthenticationError, OpenBankingCommunicationError
from custom_components.open_banking.config_flow_handler.config_flow import OpenBankingConfigFlow
from custom_components.open_banking.config_flow_handler.subentry_flow import OpenBankingInstitutionSubentryFlow
from custom_components.open_banking.const import (
    CONF_ACCOUNT_HOLDER,
    CONF_COUNTRY,
    CONF_INSTITUTION_ID,
    CONF_INSTITUTION_NAME,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    CONF_TRANSACTION_STORAGE,
    DOMAIN,
    SANDBOX_INSTITUTION_ID,
    SUBENTRY_TYPE_INSTITUTION,
    TRANSACTION_STORAGE_ENCRYPTED,
)
from homeassistant import config_entries, data_entry_flow
from homeassistant.helpers.network import NoURLAvailableError


async def test_invalid_credentials(hass, enable_custom_integrations) -> None:
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


async def test_valid_credentials_continue_to_first_bank(hass, enable_custom_integrations) -> None:
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


async def test_api_failure_keeps_flow_open_with_connection_error(hass, enable_custom_integrations) -> None:
    """Network failures keep credential setup open with a connection error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(
        "custom_components.open_banking.config_flow_handler.config_flow.OpenBankingApiClient.async_authenticate",
        AsyncMock(side_effect=OpenBankingCommunicationError),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SECRET_ID: "valid", CONF_SECRET_KEY: "valid"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


def test_supported_subentry_type() -> None:
    """The parent flow advertises institution subentries."""
    assert OpenBankingConfigFlow.async_get_supported_subentry_types(MagicMock()) == {
        SUBENTRY_TYPE_INSTITUTION: OpenBankingInstitutionSubentryFlow
    }


async def test_connection_collects_preferences_and_lists_institutions() -> None:
    """First-bank preferences lead to the institution picker."""
    flow = OpenBankingConfigFlow()
    flow._data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_institutions = AsyncMock(return_value=[{"id": "BANK", "name": "Example Bank"}])
    flow._initial_client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_connection({CONF_COUNTRY: "GB", CONF_ACCOUNT_HOLDER: "Alex"})

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "institution"
    assert flow._institutions[SANDBOX_INSTITUTION_ID] == "Sandbox Finance"  # noqa: SLF001
    client.async_get_institutions.assert_awaited_once_with("GB")


async def test_first_connection_confirms_encrypted_transaction_storage() -> None:
    """The parent flow requires confirmation before persisting transactions."""
    flow = OpenBankingConfigFlow()
    flow._data = {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_institutions = AsyncMock(return_value=[])
    flow._initial_client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    warning = await flow.async_step_connection(
        {
            CONF_COUNTRY: "GB",
            CONF_ACCOUNT_HOLDER: "Alex",
            CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_ENCRYPTED,
        }
    )
    result = await flow.async_step_transaction_storage_warning({})

    assert warning["step_id"] == "transaction_storage_warning"
    assert result["step_id"] == "institution"
    client.async_get_institutions.assert_awaited_once_with("GB")


async def test_institution_discovery_failure_returns_to_connection() -> None:
    """Institution lookup failures preserve the connection form."""
    flow = OpenBankingConfigFlow()
    flow._data = {CONF_COUNTRY: "GB"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_institutions = AsyncMock(side_effect=OpenBankingCommunicationError("offline"))
    flow._initial_client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_institution()

    assert result["step_id"] == "connection"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NoURLAvailableError, "external_url_missing"),
        (OpenBankingCommunicationError("offline"), "cannot_connect"),
    ],
)
async def test_institution_authorization_failure_is_reported(error: Exception, expected: str) -> None:
    """Authorization startup failures keep the institution picker open."""
    flow = OpenBankingConfigFlow()
    flow._institutions = {"BANK": "Example Bank"}  # noqa: SLF001
    flow._async_start_authorization = AsyncMock(side_effect=error)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_institution({CONF_INSTITUTION_ID: "BANK"})

    assert result["step_id"] == "institution"
    assert result["errors"] == {"base": expected}


async def test_authorize_accepts_only_matching_callback() -> None:
    """The initial authorization validates state before finalization."""
    flow = OpenBankingConfigFlow()
    flow._authorization_url = "https://bank.example/authorize"  # noqa: SLF001
    flow._state_token = "expected"  # noqa: SLF001

    external = await flow.async_step_authorize()
    rejected = await flow.async_step_authorize({"state": "wrong"})
    accepted = await flow.async_step_authorize({"state": "expected"})

    assert external["type"] is data_entry_flow.FlowResultType.EXTERNAL_STEP
    assert external["url"] == "https://bank.example/authorize"
    assert rejected["reason"] == "invalid_callback"
    assert accepted["type"] is data_entry_flow.FlowResultType.EXTERNAL_STEP_DONE


@pytest.mark.parametrize(
    ("requisition", "expected"),
    [
        (OpenBankingCommunicationError("offline"), "cannot_connect"),
        ({"status": "UA"}, "authorization_incomplete"),
    ],
)
async def test_finish_rejects_failed_or_incomplete_authorization(requisition: object, expected: str) -> None:
    """The parent entry is not created without a linked requisition."""
    flow = OpenBankingConfigFlow()
    flow._data = {CONF_REQUISITION_ID: "req-1"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_requisition = AsyncMock(
        side_effect=requisition if isinstance(requisition, Exception) else None,
        return_value=None if isinstance(requisition, Exception) else requisition,
    )
    flow._initial_client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["reason"] == expected


async def test_finish_creates_parent_and_first_subentry() -> None:
    """A linked first bank atomically creates credentials and its subentry."""
    flow = OpenBankingConfigFlow()
    flow.context = {"source": config_entries.SOURCE_USER}
    flow._data = {  # noqa: SLF001
        CONF_SECRET_ID: "id",
        CONF_SECRET_KEY: "key",
        CONF_REQUISITION_ID: "req-1",
        CONF_ACCOUNT_HOLDER: "Alex",
        CONF_INSTITUTION_NAME: "Example Bank",
    }
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN"})
    flow._initial_client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"}
    assert result["subentries"][0]["unique_id"] == "req-1"
    assert CONF_SECRET_KEY not in result["subentries"][0]["data"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpenBankingAuthenticationError("invalid"), "invalid_auth"),
        (OpenBankingCommunicationError("offline"), "cannot_connect"),
    ],
)
async def test_update_credentials_reports_validation_errors(error: Exception, expected: str) -> None:
    """Credential replacement distinguishes auth and connectivity failures."""
    flow = OpenBankingConfigFlow()
    flow._async_validate = AsyncMock(side_effect=error)  # type: ignore[method-assign]  # noqa: SLF001
    entry = MagicMock()
    entry.data = {CONF_SECRET_ID: "old", CONF_SECRET_KEY: "old"}

    result = await flow._async_update_credentials(  # noqa: SLF001
        entry,
        {CONF_SECRET_ID: "new", CONF_SECRET_KEY: "new"},
        "reconfigure",
    )

    assert result["errors"] == {"base": expected}


async def test_update_credentials_reloads_entry_on_success() -> None:
    """Valid replacement credentials update and reload the parent entry."""
    flow = OpenBankingConfigFlow()
    flow._async_validate = AsyncMock()  # type: ignore[method-assign]  # noqa: SLF001
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": data_entry_flow.FlowResultType.ABORT})  # type: ignore[method-assign]
    entry = MagicMock()
    replacement = {CONF_SECRET_ID: "new", CONF_SECRET_KEY: "new"}

    await flow._async_update_credentials(entry, replacement, "reauth_confirm")  # noqa: SLF001

    flow.async_update_reload_and_abort.assert_called_once_with(entry, data=replacement)
