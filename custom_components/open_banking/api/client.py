"""Async client for the GoCardless Bank Account Data API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from aiohttp import ClientError, ClientResponse, ClientSession

from .exceptions import (
    OpenBankingAuthenticationError,
    OpenBankingCommunicationError,
    OpenBankingInvalidResponseError,
    OpenBankingRateLimitError,
)

API_BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"


@dataclass(frozen=True)
class OpenBankingRateLimit:
    """Rate limit reported for one account resource endpoint."""

    limit: int
    remaining: int
    reset_after: int


class OpenBankingApiClient:
    """Minimal native async client for the API endpoints used by the integration."""

    def __init__(self, secret_id: str, secret_key: str, session: ClientSession) -> None:
        """Initialize the client."""
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._session = session
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self.account_rate_limits: dict[tuple[str, str], OpenBankingRateLimit] = {}

    async def async_authenticate(self) -> None:
        """Generate a new access and refresh token."""
        payload = await self._request(
            "POST",
            "/token/new/",
            json={"secret_id": self._secret_id, "secret_key": self._secret_key},
            authenticated=False,
        )
        self._set_tokens(payload)

    async def async_get_institutions(self, country: str) -> list[dict[str, Any]]:
        """Return institutions available in a country."""
        payload = await self._request("GET", "/institutions/", params={"country": country.upper()})
        if not isinstance(payload, list):
            raise OpenBankingInvalidResponseError("Institutions response was not a list")
        return payload

    async def async_create_requisition(
        self,
        institution_id: str,
        redirect_url: str,
        reference: str,
    ) -> dict[str, Any]:
        """Create an institution authorization requisition."""
        return await self._request(
            "POST",
            "/requisitions/",
            json={
                "institution_id": institution_id,
                "redirect": redirect_url,
                "reference": reference,
                "user_language": "EN",
            },
        )

    async def async_get_requisition(self, requisition_id: str) -> dict[str, Any]:
        """Return a requisition."""
        return await self._request("GET", f"/requisitions/{requisition_id}/")

    async def async_delete_requisition(self, requisition_id: str) -> None:
        """Delete a requisition."""
        await self._request("DELETE", f"/requisitions/{requisition_id}/")

    async def async_get_account_details(self, account_id: str) -> dict[str, Any]:
        """Return account details."""
        return await self._request("GET", f"/accounts/{account_id}/details/")

    async def async_get_account_balances(self, account_id: str) -> dict[str, Any]:
        """Return account balances."""
        return await self._request("GET", f"/accounts/{account_id}/balances/")

    async def _async_refresh_access_token(self) -> None:
        """Exchange the refresh token for an access token."""
        if self._refresh_token is None:
            await self.async_authenticate()
            return
        payload = await self._request(
            "POST",
            "/token/refresh/",
            json={"refresh": self._refresh_token},
            authenticated=False,
        )
        access_token = payload.get("access")
        if not isinstance(access_token, str):
            raise OpenBankingInvalidResponseError("Token refresh response did not contain an access token")
        self._access_token = access_token

    def _set_tokens(self, payload: Mapping[str, Any]) -> None:
        """Validate and store tokens."""
        access_token = payload.get("access")
        refresh_token = payload.get("refresh")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise OpenBankingInvalidResponseError("Token response did not contain valid tokens")
        self._access_token = access_token
        self._refresh_token = refresh_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Perform an API request and normalize failures."""
        if authenticated and self._access_token is None:
            await self.async_authenticate()

        headers = dict(kwargs.pop("headers", {}))
        headers["Accept"] = "application/json"
        if authenticated:
            headers["Authorization"] = f"Bearer {self._access_token}"

        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                headers=headers,
                **kwargs,
            ) as response:
                if response.status == 401:
                    if authenticated and retry_auth:
                        await self._async_refresh_access_token()
                        return await self._request(
                            method,
                            path,
                            authenticated=True,
                            retry_auth=False,
                            **kwargs,
                        )
                    self._raise_authentication_error(await self._error_message(response))
                if response.status == 429:
                    retry_header = response.headers.get("X-RateLimit-Account-Success-Reset") or response.headers.get(
                        "Retry-After"
                    )
                    retry_after = int(retry_header) if retry_header and retry_header.isdigit() else None
                    self._raise_rate_limit_error(await self._error_message(response), retry_after)
                if response.status >= 400:
                    message = await self._error_message(response)
                    if response.status in {401, 403}:
                        self._raise_authentication_error(message)
                    self._raise_communication_error(message)
                if response.status == 204:
                    return {}
                self._record_account_rate_limit(path, response.headers)
                try:
                    payload = await response.json()
                except (ClientError, ValueError) as err:
                    raise OpenBankingInvalidResponseError("API response was not valid JSON") from err
        except OpenBankingAuthenticationError, OpenBankingCommunicationError, OpenBankingRateLimitError:
            raise
        except (ClientError, TimeoutError) as err:
            raise OpenBankingCommunicationError(f"Unable to communicate with GoCardless: {err}") from err

        if not isinstance(payload, (dict, list)):
            raise OpenBankingInvalidResponseError("API response had an unexpected type")
        return payload

    def _record_account_rate_limit(self, path: str, headers: Mapping[str, str]) -> None:
        """Store quota metadata returned by a successful account request."""
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "accounts" or parts[2] not in {"details", "balances", "transactions"}:
            return
        normalized = {key.lower().replace("_", "-").removeprefix("http-"): value for key, value in headers.items()}
        try:
            quota = OpenBankingRateLimit(
                limit=int(normalized["x-ratelimit-account-success-limit"]),
                remaining=int(normalized["x-ratelimit-account-success-remaining"]),
                reset_after=int(normalized["x-ratelimit-account-success-reset"]),
            )
        except KeyError, ValueError:
            return
        self.account_rate_limits[(parts[1], parts[2])] = quota

    @staticmethod
    def _raise_authentication_error(message: str) -> NoReturn:
        """Raise an authentication error from a response message."""
        raise OpenBankingAuthenticationError(message)

    @staticmethod
    def _raise_rate_limit_error(message: str, retry_after: int | None) -> NoReturn:
        """Raise a rate-limit error from a response message."""
        raise OpenBankingRateLimitError(message, retry_after)

    @staticmethod
    def _raise_communication_error(message: str) -> NoReturn:
        """Raise a communication error from a response message."""
        raise OpenBankingCommunicationError(message)

    @staticmethod
    async def _error_message(response: ClientResponse) -> str:
        """Extract a safe API error message."""
        try:
            payload = await response.json()
        except ClientError, ValueError:
            return f"GoCardless returned HTTP {response.status}"
        if isinstance(payload, dict):
            return str(payload.get("detail") or payload.get("summary") or f"HTTP {response.status}")
        return f"GoCardless returned HTTP {response.status}"
