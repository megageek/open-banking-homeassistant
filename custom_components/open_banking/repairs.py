"""Repair flows for expiring and expired bank requisitions."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

import voluptuous as vol
from yarl import URL

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .api import OpenBankingApiClient, OpenBankingApiError
from .callback import CallbackState, async_store_callback_state
from .const import (
    CALLBACK_PATH,
    CALLBACK_TTL,
    CONF_INSTITUTION_ID,
    CONF_REFERENCE,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    REQUISITION_EXPIRY_ISSUE_PREFIX,
    REQUISITION_LINKED,
)


class OpenBankingRequisitionRepairFlow(RepairsFlow):
    """Replace an expiring or expired requisition."""

    def __init__(self, entry_id: str, subentry_id: str) -> None:
        """Initialize the repair flow."""
        self._entry_id = entry_id
        self._subentry_id = subentry_id
        self._state_token: str | None = None
        self._authorization_url: str | None = None
        self._requisition_id: str | None = None
        self._reference: str | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Start the repair flow."""
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Confirm and create the replacement authorization."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders={"institution": self._institution_name()},
            )
        try:
            await self._async_start_authorization()
        except NoURLAvailableError:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "external_url_missing"},
                description_placeholders={"institution": self._institution_name()},
            )
        except OpenBankingApiError:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
                description_placeholders={"institution": self._institution_name()},
            )
        return await self.async_step_authorize()

    async def async_step_authorize(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Wait for the bank authorization callback."""
        if user_input is None:
            assert self._authorization_url is not None
            return self.async_external_step(step_id="authorize", url=self._authorization_url)
        if user_input.get("state") != self._state_token:
            return self.async_abort(reason="invalid_callback")
        return self.async_external_step_done(next_step_id="finish")

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:
        """Verify and store the replacement requisition."""
        assert self._requisition_id is not None
        try:
            requisition = await self._client().async_get_requisition(self._requisition_id)
        except OpenBankingApiError:
            return self.async_abort(reason="cannot_connect")
        if requisition.get("status") != REQUISITION_LINKED:
            return self.async_abort(reason="authorization_incomplete")

        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or (subentry := entry.subentries.get(self._subentry_id)) is None:
            return self.async_abort(reason="entry_missing")
        data = dict(subentry.data)
        data[CONF_REQUISITION_ID] = self._requisition_id
        data[CONF_REFERENCE] = self._reference
        self.hass.config_entries.async_update_subentry(
            entry,
            subentry,
            data=data,
            unique_id=self._requisition_id,
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_create_entry(data={})

    async def _async_start_authorization(self) -> None:
        """Create a replacement requisition and callback state."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or (subentry := entry.subentries.get(self._subentry_id)) is None:
            raise OpenBankingApiError("Bank connection no longer exists")
        external_url = get_url(self.hass, prefer_external=True, allow_internal=False)
        state_token = secrets.token_urlsafe(32)
        callback_url = str(URL(external_url).with_path(CALLBACK_PATH).with_query({"state": state_token}))
        reference = uuid4().hex
        async_store_callback_state(
            self.hass,
            state_token,
            CallbackState(
                flow_id=self.flow_id,
                expires_at=dt_util.now() + CALLBACK_TTL,
                is_subentry=False,
                is_repair=True,
            ),
        )
        requisition = await self._client().async_create_requisition(
            str(subentry.data[CONF_INSTITUTION_ID]),
            callback_url,
            reference,
        )
        self._state_token = state_token
        self._authorization_url = str(requisition["link"])
        self._requisition_id = str(requisition["id"])
        self._reference = reference

    def _client(self) -> OpenBankingApiClient:
        """Build an API client from the parent entry credentials."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            raise OpenBankingApiError("Open Banking entry no longer exists")
        return OpenBankingApiClient(
            str(entry.data[CONF_SECRET_ID]),
            str(entry.data[CONF_SECRET_KEY]),
            async_get_clientsession(self.hass),
        )

    def _institution_name(self) -> str:
        """Return the bank connection title for flow placeholders."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or (subentry := entry.subentries.get(self._subentry_id)) is None:
            return "bank connection"
        return subentry.title


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a requisition repair flow."""
    if issue_id.startswith(REQUISITION_EXPIRY_ISSUE_PREFIX) and data is not None:
        entry_id = data.get("entry_id")
        subentry_id = data.get("subentry_id")
        if isinstance(entry_id, str) and isinstance(subentry_id, str):
            return OpenBankingRequisitionRepairFlow(entry_id, subentry_id)
    return ConfirmRepairFlow()
