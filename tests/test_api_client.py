"""Tests for the native async GoCardless client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.open_banking.api import (
    OpenBankingApiClient,
    OpenBankingAuthenticationError,
    OpenBankingInvalidResponseError,
    OpenBankingRateLimitError,
)


class FakeResponse:
    """Small aiohttp response double."""

    def __init__(self, status: int, payload: object, headers: dict[str, str] | None = None) -> None:
        """Initialize the response."""
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def json(self) -> object:
        """Return the configured payload."""
        return self.payload


class FakeContext:
    """Async request context double."""

    def __init__(self, response: FakeResponse) -> None:
        """Initialize the context."""
        self.response = response

    async def __aenter__(self) -> FakeResponse:
        """Enter the request context."""
        return self.response

    async def __aexit__(self, *args: object) -> None:
        """Exit the request context."""


def client_with_responses(*responses: FakeResponse) -> tuple[OpenBankingApiClient, MagicMock]:
    """Create a client whose session returns responses in order."""
    session = MagicMock()
    session.request.side_effect = [FakeContext(response) for response in responses]
    return OpenBankingApiClient("secret-id", "secret-key", session), session


async def test_authenticate_and_list_institutions() -> None:
    """Tokens are stored and attached to subsequent requests."""
    client, session = client_with_responses(
        FakeResponse(200, {"access": "access", "refresh": "refresh"}),
        FakeResponse(200, [{"id": "BANK", "name": "Bank"}]),
    )

    await client.async_authenticate()
    institutions = await client.async_get_institutions("gb")

    assert institutions == [{"id": "BANK", "name": "Bank"}]
    assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer access"
    assert session.request.call_args.kwargs["params"] == {"country": "GB"}


async def test_unauthorized_request_refreshes_token_once() -> None:
    """A rejected access token is refreshed and retried."""
    client, session = client_with_responses(
        FakeResponse(200, {"access": "old", "refresh": "refresh"}),
        FakeResponse(401, {"detail": "expired"}),
        FakeResponse(200, {"access": "new"}),
        FakeResponse(200, {"account": {"currency": "GBP"}}),
    )

    await client.async_authenticate()
    details = await client.async_get_account_details("account")

    assert details["account"]["currency"] == "GBP"
    assert session.request.call_count == 4


async def test_invalid_credentials_raise_authentication_error() -> None:
    """Credential rejection is distinguished from communication failures."""
    client, _ = client_with_responses(FakeResponse(401, {"detail": "bad credentials"}))

    with pytest.raises(OpenBankingAuthenticationError, match="bad credentials"):
        await client.async_authenticate()


async def test_rate_limit_exposes_retry_after() -> None:
    """HTTP 429 includes retry timing for the coordinator."""
    client, _ = client_with_responses(
        FakeResponse(200, {"access": "access", "refresh": "refresh"}),
        FakeResponse(429, {"detail": "wait"}, {"Retry-After": "120"}),
    )
    await client.async_authenticate()

    with pytest.raises(OpenBankingRateLimitError) as caught:
        await client.async_get_account_balances("account")

    assert caught.value.retry_after == 120


async def test_invalid_token_payload_is_rejected() -> None:
    """Malformed token responses cannot create a partially authenticated client."""
    client, _ = client_with_responses(FakeResponse(200, {"access": "only-access"}))

    with pytest.raises(OpenBankingInvalidResponseError):
        await client.async_authenticate()
