"""Exceptions raised by the GoCardless Bank Account Data client."""

from __future__ import annotations


class OpenBankingApiError(Exception):
    """Base API error."""


class OpenBankingAuthenticationError(OpenBankingApiError):
    """Credentials or tokens were rejected."""


class OpenBankingCommunicationError(OpenBankingApiError):
    """The API could not be reached."""


class OpenBankingInvalidResponseError(OpenBankingApiError):
    """The API returned an unexpected response."""


class OpenBankingRateLimitError(OpenBankingApiError):
    """The API rate limit was reached."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        """Initialize the rate-limit error."""
        super().__init__(message)
        self.retry_after = retry_after
