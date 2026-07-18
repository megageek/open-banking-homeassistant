# Open Banking for Home Assistant

A Home Assistant custom integration for account balances from the
[GoCardless Bank Account Data API](https://developer.gocardless.com/bank-account-data/overview).

This is an independent, community-developed integration and is not affiliated
with or endorsed by GoCardless. GoCardless is a trademark of GoCardless Ltd.

> [!WARNING]
> Version 0.6.0 changes the integration domain from `nordigen` to `open_banking`.
> Remove the old integration and YAML configuration before installing this release.

## Features

- UI configuration with GoCardless user secrets
- Multiple bank connections under one GoCardless account
- Browser-based bank authorization with an automatic Home Assistant callback
- Monetary balance sensors using each account's native currency
- Diagnostic connection-status, last-refresh, and next-refresh sensors
- Configurable daily refresh count and active refresh window

## Requirements

- Home Assistant 2026.4 or newer
- HACS 2.0.5 or newer when installing through HACS
- GoCardless Bank Account Data user secrets
- A working external Home Assistant URL for the bank authorization callback

## Installation

### HACS

1. Add `megageek/open-banking-homeassistant` as a custom integration repository.
2. Install **Open Banking via GoCardless**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/open_banking` into your Home Assistant
`custom_components` directory, then restart Home Assistant.

## Configuration

1. In Home Assistant, open **Settings → Devices & services → Add integration**.
2. Select **Open Banking via GoCardless**.
3. Enter the secret ID and secret key from GoCardless Bank Account Data.
4. Select a country and institution.
5. Complete authorization on the bank's website. The browser returns to Home
   Assistant and completes the connection automatically.

Additional institutions can be added as bank connections beneath the same
GoCardless account entry. By default, each connection refreshes four times per
day between 07:00 and 22:00 local time. Refreshes are distributed evenly across
that window and automatically respect any stricter rate limit reported by the
bank.

The account-holder label is a Home Assistant display label that helps identify
the person or profile connected to a bank; it is not sent to the bank as an
account-holder name. Selected balance types determine which balance sensors
Home Assistant creates when the bank returns those types.

## Upgrading from `nordigen`

The domain change cannot be migrated automatically by Home Assistant:

1. Remove the old Nordigen integration and its YAML configuration.
2. Remove any remaining `custom_components/nordigen` directory.
3. Install version 0.6.0 and restart Home Assistant.
4. Add **Open Banking via GoCardless** through the UI and reconnect each bank.
5. Update automations and dashboards to use the newly created entity IDs.

## Development

Open the repository in its DevContainer, then use:

```bash
script/check
script/test
script/hassfest
script/develop
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and the documentation under
[`docs/development`](docs/development/) for the complete workflow.

## Security and privacy

API secrets are stored in the Home Assistant config entry. Diagnostics redact
secrets, account-holder labels, requisition IDs, account identifiers, IBANs,
BBANs, and account owner data. Balance entities do not expose authorization
links or personal bank metadata.

## License

MIT
