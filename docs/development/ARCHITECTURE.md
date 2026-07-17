# Architecture

Open Banking is a config-entry-only Home Assistant integration for GoCardless
Bank Account Data.

## Configuration model

One parent config entry represents a GoCardless credential pair. Institution
connections are Home Assistant config subentries so credentials are stored once
while each bank retains its own requisition, account-holder label, balance-type
selection, and polling interval.

The parent flow validates credentials and immediately chains into the first
institution subentry flow. Bank authorization uses an external config-flow step
and the unauthenticated `/api/open_banking/callback` endpoint. The callback is
protected by a random, single-use state value with a 30-minute expiry.

## Runtime data flow

```text
Config entry credentials
        │
        ▼
OpenBankingApiClient
        │
        ├── institution subentry ── OpenBankingDataUpdateCoordinator
        │                                  │
        │                                  ├── connection status sensor
        │                                  └── account balance sensors
        └── additional subentries follow the same pattern
```

The client uses Home Assistant's shared aiohttp session and implements only the
required GoCardless v2 endpoints. It owns access/refresh tokens and translates
HTTP, authentication, invalid-response, and rate-limit failures into typed
exceptions.

Each subentry has one coordinator. A refresh loads its requisition, account
details, and balances. The default four-hour interval is intentionally
conservative because rate limits are imposed per bank account.

## Entity and device model

- Each institution connection is a service device with a diagnostic enum status
  sensor.
- Each returned bank account is a child device with one monetary sensor for each
  selected balance type present in the API response.
- Entity unique IDs use opaque GoCardless account/requisition identifiers; no
  personal bank fields are published as state attributes.

## Security

Credentials remain in parent config-entry data. Diagnostics redact secrets,
account-holder labels, requisition/account data, IBANs, BBANs, and owner names.
Authorization callback state is removed on first use and cannot be replayed.
