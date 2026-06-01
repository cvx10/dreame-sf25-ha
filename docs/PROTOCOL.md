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
A telemetry heartbeat (time + temperature) arrives roughly every 60 s; full status
blocks arrive on state changes (start/pause/stop/lid).

## Confirmed property map
Verified by correlating MQTT messages with physical actions during BOTH a
drying cycle (2026-05-31) and a self-cleaning cycle (2026-06-01).

| siid/piid | Meaning | Values |
|-----------|---------|--------|
| 1/6  | Program/recipe code (string) | `m01` — constant across drying AND cleaning, so it is NOT the operation selector. Meaning of suffix unconfirmed. |
| 2/1  | Status | 1=running, 2=idle, 3=finishing (seen transiently on stop) |
| 2/2  | Lid alert | 0=ok, 1=lid open |
| 2/3  | **Operation / mode** | **0=drying, 2=cleaning, -1=idle/stopped** |
| 2/10 | Run flag | 1=running, 0=paused, -1=stopped |
| 2/11 | Time remaining (min) | counts down 1/min; **frozen while paused**; 0 on stop; **360 for drying, 90 for cleaning** at fresh start |
| 3/14 | Temperature (°C) | 0 at cold start; rises during drying (saw up to 127); stays 0 during cleaning |
| 6/11 | Lid/cover | 1=open, 0=closed |
| 1/65 | unknown | seen once = 42 (event? RSSI?) |
| 2/5  | unknown | always 0 so far |

> **Correction (2026-06-01):** Earlier we assumed `1/6` was the mode
> (`m01`=drying, `m02`=cleaning). The cleaning cycle disproved this — `1/6`
> stayed `m01` while the device cleaned. The real operation discriminator is
> **`2/3`** (0=drying, 2=cleaning). `1/6` is exposed as a separate diagnostic
> "Program" sensor.

### Other MQTT message types (not `properties_changed`)
- `_otc.info`: WiFi diagnostics — `{ap:{ssid, rssi, strength, channel}, model}`.
  Candidate for a future WiFi signal sensor.

### Observed transitions
- **Drying start** (idle→run): 2/1→1, 2/3→0, 2/10→1, 2/11→360, 3/14→0, 1/6=`m01`
- **Cleaning start** (idle→run): 2/1→1, 2/3→2, 2/10→1, 2/11→90, 1/6=`m01`
- **Pause**: 2/1→2, 2/10→0, 2/11 frozen
- **Resume**: 2/1→1, 2/10→1, 2/11 resumes
- **Stop**: 2/1→3 (briefly) then →2, 2/3→-1, 2/10→-1, 2/11→0
- **Lid open**: 6/11→1, 2/2→1
- **Lid close**: 6/11→0, 2/2→0

## Still unknown
- Meaning of the `1/6` suffix (are there m02/m03 drying recipes?); 1/65, 2/5
- Whether `2/3` has other values (e.g. 1 for a third operation)
- The command/write channel (for start/stop/mode control) — HTTP relay gives 80001;
  commands likely need an MQTT publish to a request topic (not yet reverse-engineered).
