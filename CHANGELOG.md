# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/);
this project adheres to [Semantic Versioning](https://semver.org/).

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
