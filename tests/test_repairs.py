"""Tests for requisition expiry repair flows."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.open_banking.const import (
    CONF_INSTITUTION_ID,
    CONF_REFERENCE,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    DATA_CALLBACK_STATES,
    DOMAIN,
)
from custom_components.open_banking.repairs import OpenBankingRequisitionRepairFlow, async_create_fix_flow
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.config_entries import ConfigSubentry
from homeassistant.data_entry_flow import FlowResultType


async def test_finish_replaces_linked_requisition_and_unique_id(hass) -> None:
    """A completed repair atomically replaces the stored requisition."""
    subentry = ConfigSubentry(
        data=MappingProxyType({CONF_INSTITUTION_ID: "BANK", CONF_REQUISITION_ID: "old-requisition"}),
        subentry_id="bank-1",
        subentry_type="institution",
        title="Example Bank",
        unique_id="old-requisition",
    )
    entry = MockConfigEntry(
        domain="open_banking",
        entry_id="entry-1",
        data={CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"},
        subentries_data=(subentry.as_dict(),),
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_reload = AsyncMock(return_value=True)
    flow = OpenBankingRequisitionRepairFlow(entry.entry_id, subentry.subentry_id)
    flow.hass = hass
    flow._requisition_id = "new-requisition"  # noqa: SLF001
    flow._reference = "new-reference"  # noqa: SLF001
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "LN"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    updated = entry.subentries["bank-1"]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert updated.data[CONF_REQUISITION_ID] == "new-requisition"
    assert updated.data[CONF_REFERENCE] == "new-reference"
    assert updated.unique_id == "new-requisition"
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


async def test_fix_flow_uses_issue_entry_and_subentry_ids(hass) -> None:
    """A requisition expiry issue creates the specialized repair flow."""
    flow = await async_create_fix_flow(
        hass,
        "requisition_expiry_bank-1",
        {"entry_id": "entry-1", "subentry_id": "bank-1"},
    )

    assert isinstance(flow, OpenBankingRequisitionRepairFlow)


async def test_confirm_starts_external_authorization(hass) -> None:
    """Confirming a repair presents the replacement authorization URL."""
    flow = OpenBankingRequisitionRepairFlow("entry-1", "bank-1")
    flow.hass = hass

    async def start_authorization() -> None:
        flow._authorization_url = "https://bank.example/authorize"  # noqa: SLF001

    flow._async_start_authorization = start_authorization  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"] == "https://bank.example/authorize"


async def test_authorize_rejects_wrong_callback_state() -> None:
    """A repair cannot continue with a callback for another flow."""
    flow = OpenBankingRequisitionRepairFlow("entry-1", "bank-1")
    flow._state_token = "expected"  # noqa: SLF001

    result = await flow.async_step_authorize({"state": "wrong"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_callback"


async def test_finish_rejects_incomplete_replacement(hass) -> None:
    """The old requisition remains until its replacement is linked."""
    flow = OpenBankingRequisitionRepairFlow("entry-1", "bank-1")
    flow.hass = hass
    flow._requisition_id = "new-requisition"  # noqa: SLF001
    client = MagicMock()
    client.async_get_requisition = AsyncMock(return_value={"status": "UA"})
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    result = await flow.async_step_finish()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "authorization_incomplete"


async def test_unknown_issue_uses_confirmation_fallback(hass) -> None:
    """Unknown issue IDs use Home Assistant's safe fallback flow."""
    flow = await async_create_fix_flow(hass, "unknown", None)

    assert isinstance(flow, ConfirmRepairFlow)


async def test_start_authorization_creates_repair_callback_state(hass) -> None:
    """Starting a repair creates a replacement requisition and repair callback."""
    subentry = ConfigSubentry(
        data=MappingProxyType({CONF_INSTITUTION_ID: "BANK", CONF_REQUISITION_ID: "old-requisition"}),
        subentry_id="bank-1",
        subentry_type="institution",
        title="Example Bank",
        unique_id="old-requisition",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry-1",
        data={CONF_SECRET_ID: "id", CONF_SECRET_KEY: "key"},
        subentries_data=(subentry.as_dict(),),
    )
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {DATA_CALLBACK_STATES: {}}
    flow = OpenBankingRequisitionRepairFlow(entry.entry_id, subentry.subentry_id)
    flow.hass = hass
    flow.flow_id = "repair-flow"
    client = MagicMock()
    client.async_create_requisition = AsyncMock(
        return_value={"id": "new-requisition", "link": "https://bank.example/authorize"}
    )
    flow._client = MagicMock(return_value=client)  # type: ignore[method-assign]  # noqa: SLF001

    with patch("custom_components.open_banking.repairs.get_url", return_value="https://ha.example"):
        await flow._async_start_authorization()  # noqa: SLF001

    state = next(iter(hass.data[DOMAIN][DATA_CALLBACK_STATES].values()))
    assert state.flow_id == "repair-flow"
    assert state.is_repair is True
    assert flow._requisition_id == "new-requisition"  # noqa: SLF001
    assert flow._authorization_url == "https://bank.example/authorize"  # noqa: SLF001
    client.async_create_requisition.assert_awaited_once()
