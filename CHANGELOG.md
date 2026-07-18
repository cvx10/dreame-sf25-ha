# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [0.6.5] — 2026-07-18

### Fixed
- **Cycle Progress shows 100% during the cooling phase.** When the countdown
  reaches 0 the device flips mode (`2/3`) to cooling while the run flag stays
  `1`; the progress sensor treated the zero countdown as "no active cycle" and
  went `unknown` for the whole cooling phase. It now reports 100% until the
  device actually goes idle. An absent run flag (mid-cycle HA restart) is
  treated as running, matching the Estimated Finish sensor.

## [0.6.4] — 2026-07-10

### Fixed
- **Estimated Finish survives a mid-cycle HA restart.** The run flag (`2/10`)
  is only pushed on transitions, so after a restart the coordinator never sees
  it again until the next start/stop. The finish sensor treated the missing
  flag as "not running" and stayed `unknown` for the rest of the cycle. Now
  only an explicitly non-running flag hides the finish time.
- **Estimated Finish re-anchors when the countdown holds.** Adaptive drying
  freezes `2/11` while the load is still humid, which let the stored finish
  timestamp drift into the past. The value is recomputed whenever it deviates
  more than 5 min from `now + remaining`, while staying stable across the
  normal once-a-minute ticks.

## [0.6.3] — 2026-07-10

### Added
- **Cooling mode code confirmed (`2/3` = `1`).** Captured the drying→cooling
  transition: mode flips to `1`, program `1/6` flips `m01` → `m02`, status and
  run flag stay `1`. `MODE_CODES` now maps `1` → `cooling`; unknown codes fall
  back to `running` instead of guessing `cooling`.
- Two new cooling-related service-4 properties documented: `4/4` = 90
  (plausibly planned cooling minutes) and `4/5` = 161 (unknown).

### Documentation
- Reliability caveat: a drying phase can end early with no transition push
  (countdown frozen, heater off) — state sensors stay stale until the next
  pushed transition.
- `docs/PROTOCOL.md`: drying is humidity-driven and adaptive in both
  directions — the device targets a dryness threshold on `3/2`, not a fixed
  duration (`2/11` observed jumping 1 → 119, and finishing early at 55).
  `1/65` drifted mid-cycle, ruling out the total-cycle-counter hypothesis.

## [0.6.2] — 2026-07-10

### Changed
- **`3/2` is humidity (%), `3/3` is chamber temperature (breaking).** A full
  drying-cycle capture settled the tentative v0.6.1 labels: `3/3` ramps
  30→141 °C and plateaus at 142–143 during drying; `3/2` follows a
  relative-humidity curve (~57 idle, ~71 wet-load peak, ~34 when dry). The
  Temperature entity keeps its id but now sources `3/3`; the former
  `temperature_2` entity is replaced by a Humidity sensor on `3/2`.

### Documentation
- Dashboard popup: cooling branches in the header and a snowflake progress row
  during the post-drying cooling phase.

## [0.6.1] — 2026-07-08

### Added
- **`cooling` activity state.** After drying ends the device keeps
  `run_flag=1` while the barrel cools; `activity_state()` maps running with an
  unrecognised mode to `cooling`.
- Tentative Temperature / Temperature 2 sensors on the previously unmapped
  `3/2` and `3/3` properties (relabelled in v0.6.2).

## [0.6.0] — 2026-06-11

### Changed
- **Temperature sensor is now an Energy sensor (breaking).** Property `3/14`
  turned out to be a cumulative heater-energy counter (Wh), not a temperature:
  it resets to 0 at cycle start and climbs monotonically for the whole cycle
  (reaching 525 after ~5 h — impossible for °C) instead of plateauing. The
  entity is replaced by `Energy` (`device_class: energy`, unit Wh,
  `state_class: total_increasing`, resets each cycle). The old
  `sensor.*_temperature` entity is orphaned and can be deleted.

## [0.5.0] — 2026-06-07

### Added
- **MQTT availability.** Entities now report `unavailable` while the MQTT link
  to the DreameHome broker is down, instead of showing a stale value as if it
  were live. The coordinator tracks the connection state and re-evaluates
  entity availability on connect/disconnect. As soon as the link is back, the
  restored last-known value shows again until fresh data is pushed.
- **Estimated Finish** sensor (`timestamp`): when a cycle is running, exposes
  when it is expected to end, derived from the remaining minutes. Recomputed
  only when the remaining time changes, so it stays stable between ticks.
- **Activity** sensor (`enum`): folds status + run flag + mode into one readable
  state — `drying` / `cleaning` / `paused` / `idle` / `running`. Confirmed by the
  2026-06-07 capture that `run_flag` (2/10), not `status` (2/1), is the real
  run-state discriminator (status reads 2 for idle/paused/stopped alike).

### Documentation / tests
- `docs/PROTOCOL.md`: added the run-state truth table; corrected `1/65` and `2/5`
  notes (both static, not cycle-phase indicators); noted there is no fill sensor.
- Added unit tests for `activity_state()` and the stop-vs-pause truth table
  (10/10 passing).

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
