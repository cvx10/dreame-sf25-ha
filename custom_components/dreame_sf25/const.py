"""Constants for Dreame SF25 Food Composter integration."""
from __future__ import annotations
from typing import Final

DOMAIN: Final = "dreame_sf25"
MANUFACTURER: Final = "Dreame"
MODEL: Final = "SF25"
DEVICE_MODEL_ID: Final = "dreame.fwd.u2527"

CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_COUNTRY: Final = "country"
CONF_DEVICE_ID: Final = "device_id"

# Full cycle duration for the drying mode (minutes), used to derive a progress %.
FULL_CYCLE_MINUTES: Final = 360

# ---------------------------------------------------------------------------
# MIoT property mapping for the SF25 (dreame.fwd.u2527).
# siid = Service Instance ID, piid = Property Instance ID
#
# CONFIRMED via MQTT sniffing on 2026-05-31 (tools/mqtt_sniffer.py).
# The device pushes `properties_changed` messages over MQTT; these (siid, piid)
# pairs were verified by correlating with physical actions (pause/resume/stop/
# lid open-close/start). See memory/project_overview.md for the full log.
# ---------------------------------------------------------------------------

# Property keys exposed as HA entities
PROP_MODE: Final = "mode"                   # 2/3  — current operation (drying/cleaning/idle)
PROP_PROGRAM: Final = "program"             # 1/6  — drying program/recipe code (string, e.g. m01)
PROP_STATUS: Final = "status"               # 2/1  — main status (1=running, 2=idle, 3=finishing)
PROP_LID_ALERT: Final = "lid_alert"         # 2/2  — lid-open alert (0=ok, 1=open)
PROP_RUN_FLAG: Final = "run_flag"           # 2/10 — run flag (1=run, 0=paused, -1=stopped)
PROP_TIME_REMAINING: Final = "time_remaining"  # 2/11 — remaining cycle time (minutes)
PROP_ENERGY: Final = "energy"               # 3/14 — cumulative heater energy (Wh), resets at cycle start
PROP_HUMIDITY: Final = "humidity"           # 3/2  — chamber humidity (%): idle ~57, spikes ~71 at start, dries to ~34
PROP_TEMPERATURE: Final = "temperature"     # 3/3  — chamber temperature (°C): ambient ~30 idle, plateaus ~143 drying
PROP_LID: Final = "lid"                     # 6/11 — lid/cover sensor (1=open, 0=closed)

# Confirmed MIoT property table. Format: {prop_key: {"siid": X, "piid": Y}}
# Verified by MQTT sniffing of drying AND cleaning cycles (2026-05-31 / 06-01).
PROPERTY_MAPPING: Final[dict[str, dict[str, int]]] = {
    PROP_PROGRAM:        {"siid": 1, "piid": 6},
    PROP_STATUS:         {"siid": 2, "piid": 1},
    PROP_LID_ALERT:      {"siid": 2, "piid": 2},
    PROP_MODE:           {"siid": 2, "piid": 3},
    PROP_RUN_FLAG:       {"siid": 2, "piid": 10},
    PROP_TIME_REMAINING: {"siid": 2, "piid": 11},
    PROP_ENERGY:         {"siid": 3, "piid": 14},
    PROP_HUMIDITY:       {"siid": 3, "piid": 2},
    PROP_TEMPERATURE:    {"siid": 3, "piid": 3},
    PROP_LID:            {"siid": 6, "piid": 11},
}

# Status code (2/1) → human-readable name. 3 ("finishing") seen transiently on stop.
STATUS_CODES: Final = {
    1: "running",
    2: "idle",
    3: "finishing",
}

# Run-flag code (2/10) → human-readable name
RUN_FLAG_CODES: Final = {
    1: "running",
    0: "paused",
    -1: "stopped",
}

# Operation/mode code (2/3) → human-readable name.
# CONFIRMED: drying cycle reports 0 (360 min), cleaning cycle reports 2 (90 min),
# idle/stopped reports -1. (Note: 1/6 stays 'm01' for both — it is NOT the operation.)
MODE_CODES: Final = {
    -1: "idle",
    0: "drying",
    2: "cleaning",
}

# Per-mode full cycle durations (minutes), used to derive a progress %.
MODE_DURATIONS: Final = {
    0: 360,   # drying
    2: 90,    # cleaning
}

# Unified activity state: folds status (2/1) + run_flag (2/10) + mode (2/3) into
# one readable value. The 2026-06-07 capture confirmed run_flag is the real
# run-state discriminator (status is 2 for idle/paused/stopped alike).
# 2026-07-08: after drying ends the device keeps run_flag=1 but switches mode
# to a code outside MODE_CODES while it cools down — that phase is "cooling".
ACTIVITY_STATES: Final = ["idle", "drying", "cleaning", "cooling", "paused", "running"]


def activity_state(run_flag: int | None, mode: int | None) -> str:
    """Map (run_flag, mode) to a single readable activity state.

    Pure function (no Home Assistant deps) so it can be unit-tested directly.
    Caller should only invoke this once run_flag has actually been received.
    """
    if run_flag == 1:  # running → distinguish by operation
        if mode in (0, 2):
            return {0: "drying", 2: "cleaning"}[mode]
        if mode is None or mode == -1:
            # mode not received yet (e.g. right after a restart) — can't tell.
            return "running"
        # Running with a mode code we don't recognise: observed post-drying
        # while the barrel cools (raw code not yet captured; debug log will).
        return "cooling"
    if run_flag == 0:
        return "paused"
    # run_flag -1 (stopped) and the at-rest baseline are indistinguishable.
    return "idle"
