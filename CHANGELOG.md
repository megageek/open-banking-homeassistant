# Changelog

## [0.6.0](https://github.com/megageek/open-banking-homeassistant/releases/tag/v0.6.0) (2026-07-18)

### Breaking changes

- The integration domain has changed from `nordigen` to `open_banking`, and
  YAML configuration is no longer supported. Existing installations must remove
  the old integration and configure Open Banking through the Home Assistant UI.
- Connection-status sensor values now use lowercase requisition codes.

### Features

- Added UI configuration for GoCardless credentials and multiple bank
  connections.
- Added browser-based bank authorization with automatic Home Assistant
  callbacks.
- Added dynamic account discovery and native-currency balance sensors.
- Added configurable balance types, daily refresh counts, and active refresh
  windows.
- Added quota-aware scheduling with last-refresh and next-refresh sensors.
- Added masked account identifiers to distinguish similarly named accounts.
- Added repair flows for expiring and expired bank authorizations.
- Added integration branding with light- and dark-mode icons.
- Added persisted coordinator state, automatic legacy schedule migration,
  stale-entity cleanup, and sanitized operational diagnostics.

### Fixes

- Fixed authorization callback initialization.
- Fixed duplicate and missing account entities when reconnecting institutions.
- Improved sensitive-data redaction and coordinator shutdown handling.
- Clarified configuration labels, country choices, balance types, callback
  requirements, and refresh scheduling.

### Development

- Modernized the development container, setup scripts, validation workflows,
  linting, testing, documentation, and template synchronization tooling.
