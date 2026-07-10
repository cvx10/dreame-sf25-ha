# Dreame SF25 (`dreame.fwd.u2527`) — Protocol Notes

Reverse-engineering notes for the Dreame SF25 WiFi food composter.

## Device facts
- Model: `dreame.fwd.u2527` (category `/lifeapps/fwd` = Food Waste Disposer)
- App: **DreameHome** (NOT Mi Home — Mi Home login returns code 70016)
- WiFi chipset OUI: Shanghai XinMiaoLink Technology
- Local network: **all TCP/UDP ports closed**, no local API. Cloud-only.
- HTTP MIoT `get_properties` relay → **error 80001** (device doesn't answer it)
- Real-time state is delivered via **MQTT push**.

## DreameHome cloud auth
```
POST https://eu.iot.dreame.tech:13267/dreame-auth/oauth/token
Authorization: Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=   (dreame_appv1:AP^dv@z@SQYVxN88)
Body (form): grant_type=password, scope=all, platform=IOS, type=account,
             username=<email>, password=MD5(password + "RAylYC%fmSKp7%Tq"),
             country=DE, lang=de
```
Response includes `access_token`, `refresh_token`, `expires_in`, `uid`.

Required headers on all calls:
`dreame-meta: cv=i_829`, `tenant-id: 000000`,
`dreame-rlc: 7787607c258cdd79141ec1866eb5476c` (AES-128-ECB of `eu|en|DE`, key `EETjszu*XI5znHsI`).

## Device list
```
POST https://eu.iot.dreame.tech:13267/dreame-user-iot/iotuserbind/device/listV2
Body: {sharedStatus:1, current:1, size:100, lang:de, timestamp:<ms>}
```
Returns records with `did`, `model`, `bindDomain` (MQTT broker), `masterUid`.

## MQTT (the working data path)
```
broker   : mqtts://<bindDomain>   e.g. 10000.mt.eu.iot.dreame.tech:19973  (TLS, cert not verified)
clientId : p_<random hex>
username : uid  (from login response; falls back to device masterUid)
password : access_token
topic    : /status/{did}/{uid}/{model}/eu/
```
Messages:
```json
{"id":N,"did":-100000000,
 "data":{"id":N,"method":"properties_changed",
         "params":[{"siid":2,"piid":11,"value":326,"did":"-100000000"}, ...]}}
```
A telemetry heartbeat (time remaining + energy) arrives roughly every 60 s; full status
blocks arrive on state changes (start/pause/stop/lid).

## Confirmed property map
Verified by correlating MQTT messages with physical actions during BOTH a
drying cycle (2026-05-31) and a self-cleaning cycle (2026-06-01).

| siid/piid | Meaning | Values |
|-----------|---------|--------|
| 1/6  | Program/recipe code (string) | `m01` — constant across drying AND cleaning, so it is NOT the operation selector. Meaning of suffix unconfirmed. |
| 2/1  | Status | 1=running, 2=idle, 3=finishing (seen transiently on stop) |
| 2/2  | Lid alert | 0=ok, 1=lid open |
| 2/3  | **Operation / mode** | **0=drying, 2=cleaning, -1=idle/stopped**; after drying ends the device pushes an additional unidentified code while cooling (run_flag stays 1, time=0) — raw value not yet captured, integration derives "cooling" |
| 2/10 | Run flag | 1=running, 0=paused, -1=stopped |
| 2/11 | Time remaining (min) | counts down 1/min; **frozen while paused**; 0 on stop; **360 for drying, 90 for cleaning** at fresh start. **Adaptive extension** (2026-07-10): at the nominal end the device re-evaluates — observed a clean `1 → 119` jump (load not dry yet, humidity ~25) with no other property change. Drying can exceed 360 min. |
| 3/2  | **Chamber humidity (%)** | full-cycle capture 2026-07-10: ~57 at rest (indoor RH), spikes ~71 as the wet load heats, declines to ~34 as it dries, drifts back up (45–48) after the cycle. Streams every ~5–15 s while the device is active. |
| 3/3  | **Chamber temperature (°C)** | same capture: ~30 idle (ambient), ramps to ~141 within 10 min of a drying start, plateaus 142–143 for the whole drying phase, falls to ~37 by the end of cooling. |
| 3/14 | **Cumulative heater energy (Wh)** — NOT temperature | resets to 0 at cycle start; ramps ~7→3/min during heat-up, then ~1/min; climbs monotonically (saw 525 after ~5 h of drying); stays 0 during cleaning (no heater) |
| 6/11 | Lid/cover | 1=open, 0=closed |
| 1/65 | unknown | seen `3` on 2026-06-07; on 2026-07-10 re-pushed every ~15 min during a cycle, drifting `21 → 20` mid-cycle — so NOT a monotonic cycle counter. Slowly-varying scalar (consumable/filter life? internal estimate?); meaning unresolved. |
| 2/5  | unknown — **static**, likely fault code | always `0` across idle/run/pause/stop. Probably "no error". Only expected to change on a real fault. |

> **Correction (2026-06-01):** Earlier we assumed `1/6` was the mode
> (`m01`=drying, `m02`=cleaning). The cleaning cycle disproved this — `1/6`
> stayed `m01` while the device cleaned. The real operation discriminator is
> **`2/3`** (0=drying, 2=cleaning). `1/6` is exposed as a separate diagnostic
> "Program" sensor.

> **Correction (2026-06-11):** `3/14` was long believed to be a temperature
> (the early "105→127 over 10 min" observation looked like a heat-up curve).
> A full-cycle history disproved it: the value resets to 0 at cycle start and
> climbs monotonically for the whole 6-hour cycle without ever plateauing,
> reaching 525 — impossible for °C. The increment rate (~7/min during heat-up,
> ~1/min once warm) matches a heater **energy counter in Wh** (~420 W ramp,
> then duty-cycled). It is now exposed as an Energy sensor
> (`state_class: total_increasing`).

### Other MQTT message types (not `properties_changed`)
- `_otc.info`: WiFi diagnostics — `{ap:{ssid, rssi, strength, channel}, model}`.
  Candidate for a future WiFi signal sensor.

### Observed transitions
- **Drying end → cooling** (2026-07-08, ~20:11): 2/11→0, 2/3→unidentified code
  (raw value missed — debug logging was enabled later), 2/1 and 2/10 stay 1.
  During cooling the device streams 3/2 (45↔46) and 3/3 (39↔40) every few
  seconds. Status flips to idle only when cooling completes.
- **Drying start** (idle→run): 2/1→1, 2/3→0, 2/10→1, 2/11→360, 3/14→0, 1/6=`m01`
- **Cleaning start** (idle→run): 2/1→1, 2/3→2, 2/10→1, 2/11→90, 1/6=`m01`
- **Pause**: 2/1→2, 2/10→0, 2/11 frozen
- **Resume**: 2/1→1, 2/10→1, 2/11 resumes
- **Stop**: 2/1→3 (briefly) then →2, 2/3→-1, 2/10→-1, 2/11→0
- **Lid open**: 6/11→1, 2/2→1
- **Lid close**: 6/11→0, 2/2→0

### Run-state truth table (full fresh drying cycle, 2026-06-07)
Captured a clean wake → open → fill → close → drying-start, then a
pause → resume → stop → fresh-start series. Each transition isolated by ~30 s.

| Transition | 2/1 status | 2/3 mode | 2/10 run_flag | 2/11 time | Other |
|------------|:---:|:---:|:---:|:---:|-------|
| Fresh start (drying) | 1 | 0 | 1 | 360 | 1/6=`m01` re-emitted, 3/14 reset to 0 |
| **Pause**  | 2 | 0 | **0** | **frozen** | temp not re-pushed |
| **Resume** | 1 | 0 | **1** | **continues** | picks up where frozen |
| **Stop**   | 2 | **-1** | **-1** | **0** | cycle cancelled |

Key takeaways:
- `2/1` status = **2** for idle, pause AND stop alike → it does **not** distinguish
  them. `2/10` run_flag is the real run-state discriminator (1/0/-1), backed by
  `2/3` mode (0 while paused, -1 once stopped).
- A fresh start always re-emits `1/6` (`m01`) and resets `3/14` temp to 0.
- `1/65` and `2/5` stayed put through the entire series (see notes above).
- Filling the bin produced **no** MQTT event → there is no weight/fill sensor exposed.
- Status `3` ("finishing") was **not** seen on this stop (it is transient/occasional).

## Still unknown
- Meaning of the `1/6` suffix (are there m02/m03 drying recipes?)
- `1/65` (static `3`) and `2/5` (static `0`) — values seen but semantics unconfirmed;
  neither tracks the cycle, so neither is worth a live entity yet.
- Whether `2/3` has other values (e.g. 1 for a third operation)
- The command/write channel (for start/stop/mode control) — HTTP relay gives 80001;
  commands likely need an MQTT publish to a request topic (not yet reverse-engineered).
