# Dreame SF25 Food Composter — Home Assistant Integration

A custom Home Assistant integration for the **Dreame SF25** WiFi food waste
composter / dryer (`dreame.fwd.u2527`).

> ⚠️ **Unofficial.** Built by reverse-engineering the DreameHome cloud + MQTT
> protocol. Not affiliated with or endorsed by Dreame. Use at your own risk.

## How it works

The SF25 is a **cloud-only** device — it exposes no local API (all local TCP/UDP
ports are closed). It does **not** respond to the usual Xiaomi/MIoT HTTP property
reads (they return error `80001`). Instead it **pushes state changes in real time
over MQTT** to the DreameHome cloud broker.

This integration therefore:

1. Logs in to the **DreameHome** cloud (`eu.iot.dreame.tech`) with your app
   credentials to obtain a `uid` + `access_token`.
2. Connects to the device's MQTT broker (`<bindDomain>`, TLS).
3. Subscribes to `/status/{did}/{uid}/{model}/eu/` and updates entities whenever
   a `properties_changed` message arrives.

`iot_class`: `cloud_push`.

## Entities

| Entity | Type | Source (siid/piid) | Notes |
|--------|------|--------------------|-------|
| Activity | sensor (enum) | derived | unified state: `drying` / `cleaning` / `paused` / `idle` / `running` |
| Status | sensor (enum) | 2/1 | `running` / `idle` / `finishing` |
| Run State | sensor (enum) | 2/10 | `running` / `paused` / `stopped` |
| Mode | sensor (enum) | 2/3 | `drying` / `cleaning` / `idle` |
| Program | sensor (diagnostic) | 1/6 | raw program code (e.g. `m01`) |
| Time Remaining | sensor (min) | 2/11 | counts down; frozen while paused (drying 360, cleaning 90) |
| Estimated Finish | sensor (timestamp) | derived | when the running cycle is expected to end |
| Energy | sensor (Wh) | 3/14 | cumulative heater energy, resets at cycle start |
| Cycle Progress | sensor (%) | derived | from time remaining vs the per-mode cycle length |
| Lid | binary_sensor (opening) | 6/11 | open / closed |
| Lid Alert | binary_sensor (problem) | 2/2 | lid-open warning |

> Property map confirmed by MQTT sniffing on a real SF25. See
> [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the full reverse-engineering notes.
>
> Entities report `unavailable` while the MQTT link is down, rather than showing
> a stale value. The derived `Activity` sensor is the simplest single entity to
> watch on a dashboard.

This first release is **read-only** (sensors). Control entities (start/stop/pause,
mode select) are planned once the command channel is verified.

## Installation

### HACS (custom repository)
1. HACS → ⋮ → *Custom repositories*
2. Add `https://github.com/cvx10/dreame-sf25-ha`, category *Integration*
3. Install **Dreame SF25 Food Composter**, restart Home Assistant.

### Manual
Copy `custom_components/dreame_sf25/` into your HA `config/custom_components/`
directory and restart.

## Configuration
*Settings → Devices & Services → Add Integration → "Dreame SF25"*.
Enter your **DreameHome** email, password and country code (e.g. `DE`), then pick
your device from the list.

## Discovery / development tools

The `tools/` directory contains the scripts used to reverse-engineer the device.
They require the virtualenv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`

| Tool | Purpose |
|------|---------|
| `token_extractor.py` | List DreameHome devices + their DIDs |
| `mqtt_sniffer.py` | Live MQTT listener — discover properties by interacting with the device |
| `discover.py` | (Legacy) HTTP property brute-force — fails with 80001 on this model |

## Credits
Protocol groundwork from
[TA2k/ioBroker.dreame](https://github.com/TA2k/ioBroker.dreame) and
[Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum).
