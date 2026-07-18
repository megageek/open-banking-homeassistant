"""Tests for institution subentry flow outcomes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.open_banking.api import OpenBankingCommunicationError
from custom_components.open_banking.config_flow_handler.subentry_flow import OpenBankingInstitutionSubentryFlow
from custom_components.open_banking.const import (
    CONF_ACCOUNT_HOLDER,
    CONF_COUNTRY,
    CONF_INSTITUTION_ID,
    CONF_INSTITUTION_NAME,
    CONF_RECONNECT,
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_REQUISITION_ID,
    CONF_TRANSACTION_STORAGE,
    DATA_CALLBACK_STATES,
    DOMAIN,
    SANDBOX_INSTITUTION_ID,
    TRANSACTION_STORAGE_ENCRYPTED,
    TRANSACTION_STORAGE_MEMORY,
)
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.network import NoURLAvailableError


def _preferences(*, start: str = "08:00:00", end: str = "22:00:00") -> dict[str, object]:
    """Return valid connection preferences."""
    return {
        CONF_ACCOUNT_HOLDER: "Alex",
        CONF_COUNTRY: "GB",
        CONF_REFRESHES_PER_DAY: 4,
        CONF_REFRESH_WINDOW_START: start,
        CONF_REFRESH_WINDOW_END: end,
    }


async def test_user_rejects_invalid_refresh_window() -> None:
    """A window ending before it starts remains on the preferences form."""
    flow = OpenBankingInstitutionSubentryFlow()

    result = await flow.async_step_user(_preferences(start="22:00:00", end="08:00:00"))

    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_refresh_window"}


async def test_user_lists_institutions() -> None:
    """Valid preferences fetch the country's institution list."""
    flow = OpenBankingInstitutionSubentryFlow()
    client = MagicMock()
    client.async_get_institutions = AsyncMock(return_value=[{"id": "BANK", "name": "Example Bank"}])
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_user(_preferences())

    assert result["step_id"] == "institution"
    assert flow._institutions[SANDBOX_INSTITUTION_ID] == "Sandbox Finance"  # noqa: SLF001
    client.async_get_institutions.assert_awaited_once_with("GB")


async def test_user_confirms_encrypted_transaction_storage_before_institution() -> None:
    """New encrypted persistence requires an explicit warning confirmation."""
    flow = OpenBankingInstitutionSubentryFlow()
    client = MagicMock()
    client.async_get_institutions = AsyncMock(return_value=[])
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    warning = await flow.async_step_user(_preferences() | {CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_ENCRYPTED})
    result = await flow.async_step_transaction_storage_warning({})

    assert warning["step_id"] == "transaction_storage_warning"
    assert result["step_id"] == "institution"
    client.async_get_institutions.assert_awaited_once_with("GB")


async def test_institution_lookup_failure_returns_to_preferences() -> None:
    """Institution API failures return to the populated preferences form."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._data = _preferences()  # type: ignore[assignment]  # noqa: SLF001
    client = MagicMock()
    client.async_get_institutions = AsyncMock(side_effect=OpenBankingCommunicationError("offline"))
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_institution()

    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NoURLAvailableError, "external_url_missing"),
        (OpenBankingCommunicationError("offline"), "cannot_connect"),
    ],
)
async def test_institution_authorization_failure_is_reported(error: Exception, expected: str) -> None:
    """Subentry authorization startup errors keep the picker open."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._institutions = {"BANK": "Example Bank"}  # noqa: SLF001
    flow._async_start_authorization = AsyncMock(side_effect=error)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_institution({CONF_INSTITUTION_ID: "BANK"})

    assert result["errors"] == {"base": expected}


async def test_authorize_rejects_mismatched_callback_state() -> None:
    """Subentry authorization rejects callbacks with the wrong state token."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow.context = {"source": config_entries.SOURCE_USER}
    flow._state_token = "expected"  # noqa: SLF001

    result = await flow.async_step_authorize({"state": "wrong"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_callback"


async def test_authorize_opens_external_url_and_accepts_callback() -> None:
    """A matching callback advances the subentry authorization."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._authorization_url = "https://bank.example/authorize"  # noqa: SLF001
    flow._state_token = "expected"  # noqa: SLF001

    external = await flow.async_step_authorize()
    accepted = await flow.async_step_authorize({"state": "expected"})

    assert external["type"] is FlowResultType.EXTERNAL_STEP
    assert external["url"] == "https://bank.example/authorize"
    assert accepted["type"] is FlowResultType.EXTERNAL_STEP_DONE


async def test_finish_rejects_incomplete_authorization() -> None:
    """A subentry is not saved until its requisition is linked."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._data = {CONF_REQUISITION_ID: "req-1"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "UA"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "authorization_incomplete"


async def test_finish_reports_requisition_failure() -> None:
    """A failed final requisition lookup aborts safely."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._data = {CONF_REQUISITION_ID: "req-1"}  # noqa: SLF001
    client = MagicMock()
    client.async_get_requisition = AsyncMock(side_effect=OpenBankingCommunicationError("offline"))
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["reason"] == "cannot_connect"


async def test_finish_creates_linked_bank_subentry() -> None:
    """A linked requisition creates a uniquely identified bank subentry."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow.context = {"source": config_entries.SOURCE_USER}
    flow._data = {  # noqa: SLF001
        CONF_REQUISITION_ID: "req-1",
        CONF_ACCOUNT_HOLDER: "Alex",
        CONF_INSTITUTION_NAME: "Example Bank",
    }
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alex — Example Bank"
    assert result["unique_id"] == "req-1"


async def test_finish_reconfigure_updates_requisition_unique_id() -> None:
    """Manual reconnection replaces both requisition data and subentry identity."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow._reconfigure = True  # noqa: SLF001
    flow._data = {  # noqa: SLF001
        CONF_REQUISITION_ID: "new-requisition",
        CONF_ACCOUNT_HOLDER: "Alex",
        CONF_INSTITUTION_NAME: "Example Bank",
    }
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001
    flow._get_reconfigure_subentry = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]  # noqa: SLF001
    flow._get_entry = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]  # noqa: SLF001
    flow.async_update_reload_and_abort = MagicMock(  # type: ignore[method-assign]
        return_value={"type": FlowResultType.ABORT, "reason": "reconfigure_successful"}
    )

    await flow.async_step_finish()

    assert flow.async_update_reload_and_abort.call_args.kwargs["unique_id"] == "new-requisition"


async def test_reconfigure_updates_preferences_without_reconnecting() -> None:
    """Settings-only edits preserve the current requisition."""
    flow = OpenBankingInstitutionSubentryFlow()
    subentry = MagicMock()
    subentry.data = _preferences() | {
        CONF_INSTITUTION_NAME: "Example Bank",
        CONF_REQUISITION_ID: "req-1",
    }
    entry = MagicMock()
    flow._get_reconfigure_subentry = MagicMock(return_value=subentry)  # type: ignore[method-assign]  # noqa: SLF001
    flow._get_entry = MagicMock(return_value=entry)  # type: ignore[method-assign]  # noqa: SLF001
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": FlowResultType.ABORT})  # type: ignore[method-assign]

    form = await flow.async_step_reconfigure()
    updated = _preferences() | {CONF_RECONNECT: False}
    await flow.async_step_reconfigure(updated)

    assert form["step_id"] == "reconfigure"
    flow.async_update_reload_and_abort.assert_called_once()
    assert flow.async_update_reload_and_abort.call_args.kwargs["data"][CONF_REQUISITION_ID] == "req-1"


async def test_reconfigure_confirms_new_encrypted_storage() -> None:
    """Newly enabled encrypted persistence displays the warning step."""
    flow = OpenBankingInstitutionSubentryFlow()
    subentry = MagicMock()
    subentry.data = _preferences() | {
        CONF_INSTITUTION_NAME: "Example Bank",
        CONF_REQUISITION_ID: "req-1",
        CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_MEMORY,
    }
    flow._get_reconfigure_subentry = MagicMock(return_value=subentry)  # type: ignore[method-assign]  # noqa: SLF001
    flow._get_entry = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]  # noqa: SLF001
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": FlowResultType.ABORT})  # type: ignore[method-assign]

    warning = await flow.async_step_reconfigure(
        _preferences()
        | {
            CONF_RECONNECT: False,
            CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_ENCRYPTED,
        }
    )
    await flow.async_step_transaction_storage_warning({})

    assert warning["step_id"] == "transaction_storage_warning"
    assert flow.async_update_reload_and_abort.call_args.kwargs["data"][CONF_TRANSACTION_STORAGE] == (
        TRANSACTION_STORAGE_ENCRYPTED
    )


async def test_reconfigure_from_encrypted_to_memory_skips_warning() -> None:
    """Moving away from encrypted persistence applies immediately."""
    flow = OpenBankingInstitutionSubentryFlow()
    subentry = MagicMock()
    subentry.data = _preferences() | {
        CONF_INSTITUTION_NAME: "Example Bank",
        CONF_REQUISITION_ID: "req-1",
        CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_ENCRYPTED,
    }
    flow._get_reconfigure_subentry = MagicMock(return_value=subentry)  # type: ignore[method-assign]  # noqa: SLF001
    flow._get_entry = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]  # noqa: SLF001
    flow.async_update_reload_and_abort = MagicMock(return_value={"type": FlowResultType.ABORT})  # type: ignore[method-assign]

    result = await flow.async_step_reconfigure(
        _preferences()
        | {
            CONF_RECONNECT: False,
            CONF_TRANSACTION_STORAGE: TRANSACTION_STORAGE_MEMORY,
        }
    )

    assert result["type"] is FlowResultType.ABORT
    assert flow.async_update_reload_and_abort.call_args.kwargs["data"][CONF_TRANSACTION_STORAGE] == (
        TRANSACTION_STORAGE_MEMORY
    )


async def test_reconfigure_rejects_invalid_window() -> None:
    """Reconfiguration validates its active window before saving."""
    flow = OpenBankingInstitutionSubentryFlow()
    subentry = MagicMock()
    subentry.data = _preferences() | {CONF_INSTITUTION_NAME: "Example Bank"}
    flow._get_reconfigure_subentry = MagicMock(return_value=subentry)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_reconfigure(_preferences(start="22:00:00", end="08:00:00") | {CONF_RECONNECT: False})

    assert result["errors"] == {"base": "invalid_refresh_window"}


async def test_start_authorization_stores_callback_and_requisition(hass) -> None:
    """Starting authorization records callback state and requisition metadata."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow.hass = hass
    flow.flow_id = "flow-1"
    flow._data = {CONF_INSTITUTION_ID: "BANK"}  # noqa: SLF001
    hass.data.setdefault(DOMAIN, {})[DATA_CALLBACK_STATES] = {}
    client = MagicMock()
    client.async_create_requisition = AsyncMock(return_value={"id": "req-1", "link": "https://bank.example"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    with (
        patch(
            "custom_components.open_banking.config_flow_handler.subentry_flow.get_url",
            return_value="https://ha.example",
        ),
        patch(
            "custom_components.open_banking.config_flow_handler.subentry_flow.secrets.token_urlsafe",
            return_value="state",
        ),
    ):
        await flow._async_start_authorization()  # noqa: SLF001

    assert "state" in hass.data[DOMAIN][DATA_CALLBACK_STATES]
    assert flow._data[CONF_REQUISITION_ID] == "req-1"  # noqa: SLF001
    assert flow._authorization_url == "https://bank.example"  # noqa: SLF001


async def test_start_authorization_removes_callback_after_api_failure(hass) -> None:
    """A failed requisition does not leave usable callback state behind."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow.hass = hass
    flow.flow_id = "flow-1"
    flow._data = {CONF_INSTITUTION_ID: "BANK"}  # noqa: SLF001
    hass.data.setdefault(DOMAIN, {})[DATA_CALLBACK_STATES] = {}
    client = MagicMock()
    client.async_create_requisition = AsyncMock(side_effect=OpenBankingCommunicationError("offline"))
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    with (
        patch(
            "custom_components.open_banking.config_flow_handler.subentry_flow.get_url",
            return_value="https://ha.example",
        ),
        patch(
            "custom_components.open_banking.config_flow_handler.subentry_flow.secrets.token_urlsafe",
            return_value="state",
        ),
        pytest.raises(OpenBankingCommunicationError),
    ):
        await flow._async_start_authorization()  # noqa: SLF001

    assert "state" not in hass.data[DOMAIN][DATA_CALLBACK_STATES]
