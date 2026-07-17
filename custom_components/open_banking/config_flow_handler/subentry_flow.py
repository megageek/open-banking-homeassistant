"""Institution connection subentry flow."""

from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

import voluptuous as vol
from yarl import URL

from custom_components.open_banking.api import OpenBankingApiClient, OpenBankingApiError
from custom_components.open_banking.callback import CallbackState, async_store_callback_state
from custom_components.open_banking.const import (
    CALLBACK_PATH,
    CALLBACK_TTL,
    CONF_ACCOUNT_HOLDER,
    CONF_BALANCE_TYPES,
    CONF_COUNTRY,
    CONF_INSTITUTION_ID,
    CONF_INSTITUTION_NAME,
    CONF_RECONNECT,
    CONF_REFERENCE,
    CONF_REFRESH_INTERVAL,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    DATA_CALLBACK_STATES,
    DEFAULT_BALANCE_TYPES,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
    REQUISITION_LINKED,
)
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

COUNTRIES = [
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GB",
    "GR",
    "HR",
    "HU",
    "IE",
    "IS",
    "IT",
    "LI",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "NO",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
]


class OpenBankingInstitutionSubentryFlow(config_entries.ConfigSubentryFlow):
    """Add or reconfigure a GoCardless institution connection."""

    def __init__(self) -> None:
        """Initialize transient flow state."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._institutions: dict[str, str] = {}
        self._reconfigure = False
        self._state_token: str | None = None
        self._authorization_url: str | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Collect the country, account label, and polling preferences."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_institution()
        return self.async_show_form(step_id="user", data_schema=connection_schema(self._data))

    async def async_step_institution(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Fetch and select an institution, then start authorization."""
        errors: dict[str, str] = {}
        if not self._institutions:
            try:
                institutions = await self._client().async_get_institutions(self._data[CONF_COUNTRY])
            except OpenBankingApiError:
                return self.async_show_form(
                    step_id="user",
                    data_schema=connection_schema(self._data),
                    errors={"base": "cannot_connect"},
                )
            self._institutions = {
                str(institution["id"]): str(institution.get("name", institution["id"])) for institution in institutions
            }

        if user_input is not None:
            institution_id = user_input[CONF_INSTITUTION_ID]
            self._data[CONF_INSTITUTION_ID] = institution_id
            self._data[CONF_INSTITUTION_NAME] = self._institutions[institution_id]
            try:
                await self._async_start_authorization()
            except NoURLAvailableError:
                errors["base"] = "external_url_missing"
            except OpenBankingApiError:
                errors["base"] = "cannot_connect"
            else:
                return await self.async_step_authorize()

        return self.async_show_form(
            step_id="institution",
            data_schema=vol.Schema({vol.Required(CONF_INSTITUTION_ID): vol.In(self._institutions)}),
            errors=errors,
        )

    async def async_step_authorize(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Wait for and validate the browser callback."""
        if user_input is None:
            assert self._authorization_url is not None
            return self.async_external_step(step_id="authorize", url=self._authorization_url)
        if user_input.get("state") != self._state_token:
            return self.async_abort(reason="invalid_callback")
        return self.async_external_step_done(next_step_id="finish")

    async def async_step_finish(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Verify linkage and save the subentry."""
        try:
            requisition = await self._client().async_get_requisition(self._data[CONF_REQUISITION_ID])
        except OpenBankingApiError:
            return self.async_abort(reason="cannot_connect")
        if requisition.get("status") != REQUISITION_LINKED:
            return self.async_abort(reason="authorization_incomplete")

        title = f"{self._data[CONF_ACCOUNT_HOLDER]} — {self._data[CONF_INSTITUTION_NAME]}"
        if self._reconfigure:
            subentry = self._get_reconfigure_subentry()
            return self.async_update_reload_and_abort(
                self._get_entry(),
                subentry,
                data=self._data,
                title=title,
            )
        return self.async_create_entry(
            title=title,
            data=self._data,
            unique_id=str(self._data[CONF_REQUISITION_ID]),
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Update preferences or reconnect the bank authorization."""
        self._reconfigure = True
        subentry = self._get_reconfigure_subentry()
        if not self._data:
            self._data = dict(subentry.data)
        if user_input is None:
            schema = connection_schema(self._data, include_reconnect=True)
            return self.async_show_form(step_id="reconfigure", data_schema=schema)

        reconnect = bool(user_input.pop(CONF_RECONNECT, False))
        self._data.update(user_input)
        if not reconnect:
            title = f"{self._data[CONF_ACCOUNT_HOLDER]} — {self._data[CONF_INSTITUTION_NAME]}"
            return self.async_update_reload_and_abort(
                self._get_entry(),
                subentry,
                data=self._data,
                title=title,
            )
        return await self.async_step_institution()

    async def _async_start_authorization(self) -> None:
        """Create a requisition and callback state."""
        external_url = get_url(self.hass, prefer_external=True, allow_internal=False)
        state_token = secrets.token_urlsafe(32)
        callback_url = str(URL(external_url).with_path(CALLBACK_PATH).with_query({"state": state_token}))
        reference = uuid4().hex
        states: dict[str, CallbackState] = self.hass.data[DOMAIN][DATA_CALLBACK_STATES]
        async_store_callback_state(
            self.hass,
            state_token,
            CallbackState(
                flow_id=self.flow_id,
                expires_at=dt_util.now() + CALLBACK_TTL,
                is_subentry=True,
            ),
        )
        try:
            requisition = await self._client().async_create_requisition(
                self._data[CONF_INSTITUTION_ID],
                callback_url,
                reference,
            )
        except KeyError, OpenBankingApiError:
            states.pop(state_token, None)
            raise
        self._state_token = state_token
        self._authorization_url = str(requisition["link"])
        self._data[CONF_REFERENCE] = reference
        self._data[CONF_REQUISITION_ID] = str(requisition["id"])

    def _client(self) -> OpenBankingApiClient:
        """Build an API client from the parent entry credentials."""
        entry = self._get_entry()
        return OpenBankingApiClient(
            str(entry.data[CONF_SECRET_ID]),
            str(entry.data[CONF_SECRET_KEY]),
            async_get_clientsession(self.hass),
        )


def connection_schema(
    values: dict[str, Any],
    *,
    include_reconnect: bool = False,
) -> vol.Schema:
    """Return the institution connection preferences schema."""
    schema: dict[Any, Any] = {
        vol.Required(CONF_ACCOUNT_HOLDER, default=values.get(CONF_ACCOUNT_HOLDER, "")): cv.string,
        vol.Required(CONF_COUNTRY, default=values.get(CONF_COUNTRY, "GB")): vol.In(COUNTRIES),
        vol.Required(
            CONF_REFRESH_INTERVAL,
            default=values.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_REFRESH_INTERVAL, max=MAX_REFRESH_INTERVAL)),
        vol.Optional(
            CONF_BALANCE_TYPES,
            default=values.get(CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES),
        ): cv.multi_select({balance_type: balance_type for balance_type in DEFAULT_BALANCE_TYPES}),
    }
    if include_reconnect:
        schema[vol.Optional(CONF_RECONNECT, default=False)] = cv.boolean
    return vol.Schema(schema)
