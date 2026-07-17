"""Parent credential config flow for Open Banking."""

from __future__ import annotations

from hashlib import sha256
import secrets
from typing import Any
from uuid import uuid4

import voluptuous as vol
from yarl import URL

from custom_components.open_banking.api import OpenBankingApiClient, OpenBankingApiError, OpenBankingAuthenticationError
from custom_components.open_banking.callback import CallbackState, async_store_callback_state
from custom_components.open_banking.const import (
    CALLBACK_PATH,
    CALLBACK_TTL,
    CONF_ACCOUNT_HOLDER,
    CONF_COUNTRY,
    CONF_INSTITUTION_ID,
    CONF_INSTITUTION_NAME,
    CONF_REFERENCE,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    DATA_CALLBACK_STATES,
    DOMAIN,
    REQUISITION_LINKED,
    SUBENTRY_TYPE_INSTITUTION,
)
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.util import dt as dt_util

from .subentry_flow import OpenBankingInstitutionSubentryFlow, connection_schema


def _credentials_schema(values: dict[str, Any] | None = None) -> vol.Schema:
    """Return the credential form schema."""
    values = values or {}
    secret_selector = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    return vol.Schema(
        {
            vol.Required(CONF_SECRET_ID, default=values.get(CONF_SECRET_ID, "")): secret_selector,
            vol.Required(CONF_SECRET_KEY, default=values.get(CONF_SECRET_KEY, "")): secret_selector,
        }
    )


class OpenBankingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure GoCardless API credentials."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient initial-connection state."""
        super().__init__()
        self._data: dict[str, Any] = {}
        self._institutions: dict[str, str] = {}
        self._state_token: str | None = None
        self._authorization_url: str | None = None

    @classmethod
    def async_get_supported_subentry_types(
        cls,
        config_entry: config_entries.ConfigEntry,
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        """Return the supported bank connection subentry type."""
        return {SUBENTRY_TYPE_INSTITUTION: OpenBankingInstitutionSubentryFlow}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Validate credentials and create the parent account entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._async_validate(user_input)
            except OpenBankingAuthenticationError:
                errors["base"] = "invalid_auth"
            except OpenBankingApiError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = sha256(user_input[CONF_SECRET_ID].encode()).hexdigest()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                self._data.update(user_input)
                return await self.async_step_connection()
        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(user_input),
            errors=errors,
        )

    async def async_step_connection(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Collect settings for the first bank connection."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_institution()
        return self.async_show_form(step_id="connection", data_schema=connection_schema(self._data))

    async def async_step_institution(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Fetch and select the first institution."""
        errors: dict[str, str] = {}
        if not self._institutions:
            try:
                institutions = await self._initial_client().async_get_institutions(self._data[CONF_COUNTRY])
            except OpenBankingApiError:
                return self.async_show_form(
                    step_id="connection",
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
    ) -> config_entries.ConfigFlowResult:
        """Wait for the first bank's browser callback."""
        if user_input is None:
            assert self._authorization_url is not None
            return self.async_external_step(step_id="authorize", url=self._authorization_url)
        if user_input.get("state") != self._state_token:
            return self.async_abort(reason="invalid_callback")
        return self.async_external_step_done(next_step_id="finish")

    async def async_step_finish(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Verify and atomically create the account and first subentry."""
        try:
            requisition = await self._initial_client().async_get_requisition(self._data[CONF_REQUISITION_ID])
        except OpenBankingApiError:
            return self.async_abort(reason="cannot_connect")
        if requisition.get("status") != REQUISITION_LINKED:
            return self.async_abort(reason="authorization_incomplete")
        title = f"{self._data[CONF_ACCOUNT_HOLDER]} — {self._data[CONF_INSTITUTION_NAME]}"
        credentials = {
            CONF_SECRET_ID: self._data[CONF_SECRET_ID],
            CONF_SECRET_KEY: self._data[CONF_SECRET_KEY],
        }
        subentry_data = {
            key: value for key, value in self._data.items() if key not in {CONF_SECRET_ID, CONF_SECRET_KEY}
        }
        return self.async_create_entry(
            title="GoCardless Bank Account Data",
            data=credentials,
            subentries=[
                {
                    "data": subentry_data,
                    "subentry_type": SUBENTRY_TYPE_INSTITUTION,
                    "title": title,
                    "unique_id": str(self._data[CONF_REQUISITION_ID]),
                }
            ],
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Start credential reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Validate replacement credentials."""
        entry = self._get_reauth_entry()
        return await self._async_update_credentials(entry, user_input, "reauth_confirm")

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure account credentials."""
        entry = self._get_reconfigure_entry()
        return await self._async_update_credentials(entry, user_input, "reconfigure")

    async def _async_update_credentials(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict[str, Any] | None,
        step_id: str,
    ) -> config_entries.ConfigFlowResult:
        """Shared reauth and reconfigure implementation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._async_validate(user_input)
            except OpenBankingAuthenticationError:
                errors["base"] = "invalid_auth"
            except OpenBankingApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id=step_id,
            data_schema=_credentials_schema(dict(entry.data) | (user_input or {})),
            errors=errors,
        )

    async def _async_validate(self, data: dict[str, Any]) -> None:
        """Validate a credential pair with the API."""
        client = OpenBankingApiClient(
            data[CONF_SECRET_ID],
            data[CONF_SECRET_KEY],
            async_get_clientsession(self.hass),
        )
        await client.async_authenticate()

    def _initial_client(self) -> OpenBankingApiClient:
        """Build a client from credentials collected by this flow."""
        return OpenBankingApiClient(
            self._data[CONF_SECRET_ID],
            self._data[CONF_SECRET_KEY],
            async_get_clientsession(self.hass),
        )

    async def _async_start_authorization(self) -> None:
        """Create the initial requisition and parent-flow callback state."""
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
                is_subentry=False,
            ),
        )
        try:
            requisition = await self._initial_client().async_create_requisition(
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
