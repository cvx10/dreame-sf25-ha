# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [0.4.0] — 2026-06-01

### Added
- **State restoration across restarts.** Because the SF25 only pushes state
  (no polled read), entities used to show `unknown` after every HA restart
  until the device next pushed. Sensors now use `RestoreSensor` and binary
  sensors `RestoreEntity` to display the last known value immediately on
  startup; the live value takes over as soon as the property is pushed again.
  Fallback applies per-property, only while that property is absent from the
  coordinator.

## [0.3.1] — 2026-06-01

### Fixed
- ENUM sensors (Status / Run State / Mode) now return `None` for any unmapped
  code instead of a synthetic `unknown_<n>` string. An out-of-`options` value
  made the ENUM sensor raise, which crashed the coordinator's listener update
  ("Unexpected error updating listener"). This was hit when status code `3`
  arrived on stop. Unmapped codes now show as `unknown` without errors.

## [0.3.0] — 2026-06-01

### Changed
- **Mode is now read from `2/3`** (the real operation discriminator):
  `0`=drying, `2`=cleaning, `-1`=idle. Confirmed by capturing a self-cleaning
  cycle. The old assumption that `1/6` was the mode was wrong — `1/6` stays
  `m01` for both drying and cleaning.
- Cycle Progress now uses the per-mode duration (drying 360 min, cleaning 90 min).

### Added
- **Program** diagnostic sensor exposing the raw `1/6` code (e.g. `m01`).
- Status value `3` ("finishing"), seen transiently when a cycle is stopped.
- Documented the `_otc.info` WiFi diagnostic MQTT message (future signal sensor).

## [0.2.0] — 2026-05-31

### Added
- MQTT-push architecture (`cloud_push`): connects to the DreameHome MQTT broker
  and updates entities in real time from `properties_changed` messages.
- Confirmed MIoT property map for `dreame.fwd.u2527`, verified by live sniffing.
- Sensors: Status, Run State, Mode, Time Remaining, Temperature, Cycle Progress (derived).
- Binary sensors: Lid (opening), Lid Alert (problem).
- `docs/PROTOCOL.md` reverse-engineering notes; unit tests replaying a real capture.
- Discovery tooling: `tools/token_extractor.py`, `tools/mqtt_sniffer.py`.

### Changed
- Switched cloud backend from Xiaomi Mi Home to DreameHome (`eu.iot.dreame.tech`).

### Known limitations
- Read-only: no control entities yet (command channel not verified).
- `m02` mode label (cleaning) presumed, not yet captured.

## [0.1.0] — 2026-05-29

### Added
- Initial scaffold: config flow, coordinator, and Mi Home cloud client (later replaced).
