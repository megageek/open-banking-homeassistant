"""Tests for institution subentry flow outcomes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.open_banking.config_flow_handler.subentry_flow import OpenBankingInstitutionSubentryFlow
from custom_components.open_banking.const import CONF_ACCOUNT_HOLDER, CONF_INSTITUTION_NAME, CONF_REQUISITION_ID
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType


async def test_authorize_rejects_mismatched_callback_state() -> None:
    """Subentry authorization rejects callbacks with the wrong state token."""
    flow = OpenBankingInstitutionSubentryFlow()
    flow.context = {"source": config_entries.SOURCE_USER}
    flow._state_token = "expected"  # noqa: SLF001

    result = await flow.async_step_authorize({"state": "wrong"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_callback"


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
