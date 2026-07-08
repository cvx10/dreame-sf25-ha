"""Unit tests for the SF25 property mapping and MQTT message handling.

These tests do NOT require Home Assistant — they import the standalone modules
via a package stub (same trick the tools use) and replay real captured MQTT data.

Run:  .venv/bin/python3 -m pytest tests/ -v
  or: .venv/bin/python3 tests/test_property_mapping.py
"""
from __future__ import annotations

import json
import os
import sys
import types

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

# Stub the package so const.py / mqtt_client.py import without triggering __init__.py
_pkg = types.ModuleType("custom_components")
_subpkg = types.ModuleType("custom_components.dreame_sf25")
_subpkg.__path__ = [os.path.join(_ROOT, "custom_components", "dreame_sf25")]
_subpkg.__package__ = "custom_components.dreame_sf25"
sys.modules.setdefault("custom_components", _pkg)
sys.modules["custom_components.dreame_sf25"] = _subpkg

from custom_components.dreame_sf25 import const  # noqa: E402
from custom_components.dreame_sf25.mqtt_client import DreameMqttClient  # noqa: E402

_REVERSE = {(v["siid"], v["piid"]): k for k, v in const.PROPERTY_MAPPING.items()}


def test_property_mapping_is_complete_and_unique():
    # 8 confirmed properties + 2 tentative temperature probes (3/2, 3/3)
    assert len(const.PROPERTY_MAPPING) == 10
    # No duplicate (siid, piid) pairs
    pairs = [(v["siid"], v["piid"]) for v in const.PROPERTY_MAPPING.values()]
    assert len(pairs) == len(set(pairs))


def test_known_siid_piid_pairs():
    assert const.PROPERTY_MAPPING[const.PROP_TIME_REMAINING] == {"siid": 2, "piid": 11}
    assert const.PROPERTY_MAPPING[const.PROP_LID] == {"siid": 6, "piid": 11}
    # Mode is the operation discriminator at 2/3 (drying=0, cleaning=2, idle=-1).
    assert const.PROPERTY_MAPPING[const.PROP_MODE] == {"siid": 2, "piid": 3}
    # 1/6 is a separate program/recipe code string, exposed as "program".
    assert const.PROPERTY_MAPPING[const.PROP_PROGRAM] == {"siid": 1, "piid": 6}
    # Tentative temperature probes seen streaming during the cooling phase.
    assert const.PROPERTY_MAPPING[const.PROP_TEMPERATURE] == {"siid": 3, "piid": 2}
    assert const.PROPERTY_MAPPING[const.PROP_TEMPERATURE_2] == {"siid": 3, "piid": 3}


def test_mode_codes():
    assert const.MODE_CODES[0] == "drying"
    assert const.MODE_CODES[2] == "cleaning"
    assert const.MODE_CODES[-1] == "idle"


def test_mqtt_topic_format():
    c = DreameMqttClient(
        "10000.mt.eu.iot.dreame.tech:19973",
        "EXAMPLEUID",
        "tok",
        "-100000000",
        "dreame.fwd.u2527",
        lambda x: None,
    )
    assert c._topic == "/status/-100000000/EXAMPLEUID/dreame.fwd.u2527/eu/"
    assert c._host == "10000.mt.eu.iot.dreame.tech"
    assert c._port == 19973


def _replay(messages: list[dict]) -> dict:
    """Replay properties_changed messages through the reverse mapping."""
    state: dict = {}
    for m in messages:
        for p in m["payload"]["data"]["params"]:
            key = _REVERSE.get((p["siid"], p["piid"]))
            if key:
                state[key] = p["value"]
    return state


def test_replay_sample_capture():
    """Replay the sanitized sample capture fixture and assert reconstructed state."""
    cap_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_capture.json")
    cap = json.load(open(cap_path))
    state = _replay(cap["message_log"])

    # Fixture = drying cycle start, heartbeat, then a lid open/close
    assert state["mode"] == 0          # 2/3 = 0 → drying
    assert state["program"] == "m01"   # 1/6 = raw program code
    assert state["status"] == 1
    assert state["run_flag"] == 1
    assert state["lid"] == 0           # ends closed after open/close
    assert state["lid_alert"] == 0     # alert cleared after close
    assert state["time_remaining"] == 354
    assert state["energy"] == 15

    # Value transforms
    assert const.MODE_CODES[state["mode"]] == "drying"
    assert const.STATUS_CODES[state["status"]] == "running"
    assert const.RUN_FLAG_CODES[state["run_flag"]] == "running"


def test_cleaning_cycle_start():
    """A cleaning start reports 2/3=2 (cleaning) with a 90-min timer; 1/6 stays m01."""
    start = [{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 2, "piid": 1, "value": 1},
        {"siid": 2, "piid": 3, "value": 2},     # operation = cleaning
        {"siid": 2, "piid": 10, "value": 1},
        {"siid": 2, "piid": 11, "value": 90},    # cleaning duration
        {"siid": 1, "piid": 6, "value": "m01"},  # program code unchanged
    ]}}}]
    s = _replay(start)
    assert s["mode"] == 2
    assert const.MODE_CODES[s["mode"]] == "cleaning"
    assert s["program"] == "m01"
    assert s["time_remaining"] == 90
    # Progress for cleaning uses the 90-min duration
    assert const.MODE_DURATIONS[2] == 90


def test_lid_open_close_cycle():
    """Lid open sets 6/11=1 and 2/2=1; close returns both to 0."""
    opened = [{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 6, "piid": 11, "value": 1},
        {"siid": 2, "piid": 2, "value": 1},
    ]}}}]
    closed = [{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 6, "piid": 11, "value": 0},
        {"siid": 2, "piid": 2, "value": 0},
    ]}}}]
    assert _replay(opened) == {"lid": 1, "lid_alert": 1}
    assert _replay(closed) == {"lid": 0, "lid_alert": 0}


def test_pause_freezes_time():
    """Pause should freeze time_remaining and set run_flag=0."""
    running = [{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 2, "piid": 1, "value": 1},
        {"siid": 2, "piid": 10, "value": 1},
        {"siid": 2, "piid": 11, "value": 326},
    ]}}}]
    paused = [{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 2, "piid": 1, "value": 2},
        {"siid": 2, "piid": 10, "value": 0},
        {"siid": 2, "piid": 11, "value": 326},  # unchanged = frozen
    ]}}}]
    s1 = _replay(running)
    s2 = _replay(paused)
    assert s1["run_flag"] == 1 and s2["run_flag"] == 0
    assert s1["time_remaining"] == s2["time_remaining"] == 326


def test_activity_state_mapping():
    """The unified activity state folds run_flag + mode into one value."""
    # Running → distinguished by mode
    assert const.activity_state(1, 0) == "drying"
    assert const.activity_state(1, 2) == "cleaning"
    assert const.activity_state(1, None) == "running"   # running, mode not yet received
    assert const.activity_state(1, -1) == "running"     # running, mode says idle (transient)
    # 2026-07-08: post-drying the device keeps run_flag=1 with an unrecognised
    # mode code while the barrel cools down.
    assert const.activity_state(1, 99) == "cooling"
    # Paused
    assert const.activity_state(0, 0) == "paused"
    # Stopped / at-rest both collapse to idle
    assert const.activity_state(-1, -1) == "idle"
    assert const.activity_state(None, None) == "idle"
    # Every result is a declared ENUM option
    for rf in (1, 0, -1, None):
        for md in (0, 2, -1, None, 99):
            assert const.activity_state(rf, md) in const.ACTIVITY_STATES


def test_stop_vs_pause_truth_table():
    """2026-06-07 capture: stop resets mode/time, pause freezes them.

    Confirms run_flag is the discriminator (status is 2 for both pause and stop).
    """
    paused = _replay([{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 2, "piid": 1, "value": 2},    # status idle-like
        {"siid": 2, "piid": 3, "value": 0},    # mode still drying
        {"siid": 2, "piid": 10, "value": 0},   # run_flag paused
        {"siid": 2, "piid": 11, "value": 354}, # time frozen
    ]}}}])
    stopped = _replay([{"payload": {"data": {"method": "properties_changed", "params": [
        {"siid": 2, "piid": 1, "value": 2},    # status idle-like (same as pause!)
        {"siid": 2, "piid": 3, "value": -1},   # mode reset
        {"siid": 2, "piid": 10, "value": -1},  # run_flag stopped
        {"siid": 2, "piid": 11, "value": 0},   # time wiped
    ]}}}])
    # Same status, different run_flag → run_flag is the discriminator.
    assert paused["status"] == stopped["status"] == 2
    assert const.activity_state(paused["run_flag"], paused["mode"]) == "paused"
    assert const.activity_state(stopped["run_flag"], stopped["mode"]) == "idle"
    assert paused["time_remaining"] == 354 and stopped["time_remaining"] == 0


if __name__ == "__main__":
    # Allow running without pytest
    import traceback

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(funcs) - failed}/{len(funcs)} tests passed")
    sys.exit(1 if failed else 0)
