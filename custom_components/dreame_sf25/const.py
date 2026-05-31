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
PROP_MODE: Final = "mode"                   # 1/6  — composting mode (string code)
PROP_STATUS: Final = "status"               # 2/1  — main status (1=running, 2=idle)
PROP_LID_ALERT: Final = "lid_alert"         # 2/2  — lid-open alert (0=ok, 1=open)
PROP_CYCLE_ACTIVE: Final = "cycle_active"   # 2/3  — cycle active sub-state (0=active, -1=stopped)
PROP_RUN_FLAG: Final = "run_flag"           # 2/10 — run flag (1=run, 0=paused, -1=stopped)
PROP_TIME_REMAINING: Final = "time_remaining"  # 2/11 — remaining cycle time (minutes)
PROP_TEMPERATURE: Final = "temperature"     # 3/14 — internal temperature (°C)
PROP_LID: Final = "lid"                     # 6/11 — lid/cover sensor (1=open, 0=closed)

# Confirmed MIoT property table. Format: {prop_key: {"siid": X, "piid": Y}}
PROPERTY_MAPPING: Final[dict[str, dict[str, int]]] = {
    PROP_MODE:           {"siid": 1, "piid": 6},
    PROP_STATUS:         {"siid": 2, "piid": 1},
    PROP_LID_ALERT:      {"siid": 2, "piid": 2},
    PROP_CYCLE_ACTIVE:   {"siid": 2, "piid": 3},
    PROP_RUN_FLAG:       {"siid": 2, "piid": 10},
    PROP_TIME_REMAINING: {"siid": 2, "piid": 11},
    PROP_TEMPERATURE:    {"siid": 3, "piid": 14},
    PROP_LID:            {"siid": 6, "piid": 11},
}

# Status code (2/1) → human-readable name
STATUS_CODES: Final = {
    1: "running",
    2: "idle",
}

# Run-flag code (2/10) → human-readable name
RUN_FLAG_CODES: Final = {
    1: "running",
    0: "paused",
    -1: "stopped",
}

# Mode code (1/6, string) → human-readable name
# 'm01' confirmed = Séchage (Drying). 'm02' presumed = Nettoyage (Cleaning).
MODE_CODES: Final = {
    "m01": "drying",
    "m02": "cleaning",
}
