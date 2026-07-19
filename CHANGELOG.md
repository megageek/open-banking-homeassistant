# Changelog

## [0.6.3](https://github.com/megageek/open-banking-homeassistant/compare/v0.6.2...v0.6.3) (2026-07-19)


### Bug Fixes

* **sensor:** use valid monetary state class ([13703e5](https://github.com/megageek/open-banking-homeassistant/commit/13703e50909246a1ee1199e4e7765d9c300e9565))

## [0.6.2](https://github.com/megageek/open-banking-homeassistant/compare/v0.6.1...v0.6.2) (2026-07-18)


### Bug Fixes

* **config-flow:** clarify transaction storage text ([2e5d436](https://github.com/megageek/open-banking-homeassistant/commit/2e5d436bdffb359804536b7beced3c99fb75e67d))

## [0.6.1](https://github.com/megageek/open-banking-homeassistant/compare/v0.6.0...v0.6.1) (2026-07-18)


### Features

* **transactions:** add pending period sensors ([e303c36](https://github.com/megageek/open-banking-homeassistant/commit/e303c360b53130b152fd930b755807b04b76b0da))
* **transactions:** add tiered transaction support ([f695dbd](https://github.com/megageek/open-banking-homeassistant/commit/f695dbd6c096b91d0d17e2eeafa2951ec65e24cb))
* **transactions:** add transaction update triggers ([6e9c8ea](https://github.com/megageek/open-banking-homeassistant/commit/6e9c8eae40c8c4163c1e749b6fa9e872fd4fb252))


### Bug Fixes

* **transactions:** clean up stale summary entities ([7c33cf8](https://github.com/megageek/open-banking-homeassistant/commit/7c33cf86e90678fc40c392d18836385eac5a2e51))

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
