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
    CONF_REFRESH_WINDOW_END,
    CONF_REFRESH_WINDOW_START,
    CONF_REFRESHES_PER_DAY,
    CONF_REQUISITION_ID,
    CONF_SECRET_ID,
    CONF_SECRET_KEY,
    CONF_TRANSACTION_STORAGE,
    DEFAULT_BALANCE_TYPES,
    DEFAULT_REFRESH_WINDOW_END,
    DEFAULT_REFRESH_WINDOW_START,
    DEFAULT_REFRESHES_PER_DAY,
    DEFAULT_TRANSACTION_STORAGE,
    MAX_REFRESHES_PER_DAY,
    MIN_REFRESHES_PER_DAY,
    REQUISITION_LINKED,
    SANDBOX_INSTITUTION_ID,
    SANDBOX_INSTITUTION_NAME,
    TRANSACTION_STORAGE_DISABLED,
    TRANSACTION_STORAGE_ENCRYPTED,
    TRANSACTION_STORAGE_MEMORY,
)
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode, TimeSelector
from homeassistant.util import dt as dt_util

COUNTRIES = {
    "AT": "Austria (AT)",
    "BE": "Belgium (BE)",
    "BG": "Bulgaria (BG)",
    "CY": "Cyprus (CY)",
    "CZ": "Czechia (CZ)",
    "DE": "Germany (DE)",
    "DK": "Denmark (DK)",
    "EE": "Estonia (EE)",
    "ES": "Spain (ES)",
    "FI": "Finland (FI)",
    "FR": "France (FR)",
    "GB": "United Kingdom (GB)",
    "GR": "Greece (GR)",
    "HR": "Croatia (HR)",
    "HU": "Hungary (HU)",
    "IE": "Ireland (IE)",
    "IS": "Iceland (IS)",
    "IT": "Italy (IT)",
    "LI": "Liechtenstein (LI)",
    "LT": "Lithuania (LT)",
    "LU": "Luxembourg (LU)",
    "LV": "Latvia (LV)",
    "MT": "Malta (MT)",
    "NL": "Netherlands (NL)",
    "NO": "Norway (NO)",
    "PL": "Poland (PL)",
    "PT": "Portugal (PT)",
    "RO": "Romania (RO)",
    "SE": "Sweden (SE)",
    "SI": "Slovenia (SI)",
    "SK": "Slovakia (SK)",
}

BALANCE_TYPES = {
    "closingBooked": "Closing booked",
    "expected": "Expected",
    "forwardAvailable": "Forward available",
    "interimAvailable": "Interim available",
    "interimBooked": "Interim booked",
    "nonInvoiced": "Not invoiced",
    "openingBooked": "Opening booked",
}
TRANSACTION_STORAGE_MODES = {
    TRANSACTION_STORAGE_DISABLED: "Disabled",
    TRANSACTION_STORAGE_MEMORY: "Memory only",
    TRANSACTION_STORAGE_ENCRYPTED: "Encrypted persistent",
}


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
        self._warning_next_step: str | None = None
        self._pending_reconnect = False

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Collect the country, account label, and polling preferences."""
        if user_input is not None:
            if not _valid_refresh_window(user_input):
                return self.async_show_form(
                    step_id="user",
                    data_schema=connection_schema(user_input),
                    errors={"base": "invalid_refresh_window"},
                )
            self._data.update(user_input)
            if user_input.get(CONF_TRANSACTION_STORAGE, DEFAULT_TRANSACTION_STORAGE) == TRANSACTION_STORAGE_ENCRYPTED:
                self._warning_next_step = "institution"
                return await self.async_step_transaction_storage_warning()
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
            self._institutions.setdefault(SANDBOX_INSTITUTION_ID, SANDBOX_INSTITUTION_NAME)

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
                unique_id=str(self._data[CONF_REQUISITION_ID]),
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
        previous_mode = str(subentry.data.get(CONF_TRANSACTION_STORAGE, DEFAULT_TRANSACTION_STORAGE))
        if not _valid_refresh_window(user_input):
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=connection_schema(user_input, include_reconnect=True),
                errors={"base": "invalid_refresh_window"},
            )
        self._data.update(user_input)
        self._pending_reconnect = reconnect
        if (
            user_input.get(CONF_TRANSACTION_STORAGE, DEFAULT_TRANSACTION_STORAGE) == TRANSACTION_STORAGE_ENCRYPTED
            and previous_mode != TRANSACTION_STORAGE_ENCRYPTED
        ):
            self._warning_next_step = "reconfigure"
            return await self.async_step_transaction_storage_warning()
        return await self._async_finish_reconfigure()

    async def async_step_transaction_storage_warning(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """Confirm encrypted local transaction persistence."""
        if user_input is None:
            return self.async_show_form(step_id="transaction_storage_warning", data_schema=vol.Schema({}))
        if self._warning_next_step == "institution":
            return await self.async_step_institution()
        return await self._async_finish_reconfigure()

    async def _async_finish_reconfigure(self) -> config_entries.SubentryFlowResult:
        """Apply reconfiguration or reconnect authorization."""
        subentry = self._get_reconfigure_subentry()
        reconnect = self._pending_reconnect
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
        states = async_store_callback_state(
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
            CONF_REFRESHES_PER_DAY,
            default=values.get(CONF_REFRESHES_PER_DAY, DEFAULT_REFRESHES_PER_DAY),
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_REFRESHES_PER_DAY,
                max=MAX_REFRESHES_PER_DAY,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_REFRESH_WINDOW_START,
            default=values.get(CONF_REFRESH_WINDOW_START, DEFAULT_REFRESH_WINDOW_START),
        ): TimeSelector(),
        vol.Required(
            CONF_REFRESH_WINDOW_END,
            default=values.get(CONF_REFRESH_WINDOW_END, DEFAULT_REFRESH_WINDOW_END),
        ): TimeSelector(),
        vol.Optional(
            CONF_BALANCE_TYPES,
            default=values.get(CONF_BALANCE_TYPES, DEFAULT_BALANCE_TYPES),
        ): cv.multi_select(BALANCE_TYPES),
        vol.Required(
            CONF_TRANSACTION_STORAGE,
            default=values.get(CONF_TRANSACTION_STORAGE, DEFAULT_TRANSACTION_STORAGE),
        ): vol.In(TRANSACTION_STORAGE_MODES),
    }
    if include_reconnect:
        schema[vol.Optional(CONF_RECONNECT, default=False)] = cv.boolean
    return vol.Schema(schema)


def _valid_refresh_window(values: dict[str, Any]) -> bool:
    """Return whether the active window starts before it ends."""
    return str(values[CONF_REFRESH_WINDOW_START]) < str(values[CONF_REFRESH_WINDOW_END])
