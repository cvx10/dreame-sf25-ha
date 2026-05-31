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
    # All 8 confirmed properties present
    assert len(const.PROPERTY_MAPPING) == 8
    # No duplicate (siid, piid) pairs
    pairs = [(v["siid"], v["piid"]) for v in const.PROPERTY_MAPPING.values()]
    assert len(pairs) == len(set(pairs))


def test_known_siid_piid_pairs():
    assert const.PROPERTY_MAPPING[const.PROP_TIME_REMAINING] == {"siid": 2, "piid": 11}
    assert const.PROPERTY_MAPPING[const.PROP_LID] == {"siid": 6, "piid": 11}
    assert const.PROPERTY_MAPPING[const.PROP_MODE] == {"siid": 1, "piid": 6}


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
    assert state["mode"] == "m01"
    assert state["status"] == 1
    assert state["run_flag"] == 1
    assert state["lid"] == 0           # ends closed after open/close
    assert state["lid_alert"] == 0     # alert cleared after close
    assert state["time_remaining"] == 354
    assert state["temperature"] == 15

    # Value transforms
    assert const.MODE_CODES[state["mode"]] == "drying"
    assert const.STATUS_CODES[state["status"]] == "running"
    assert const.RUN_FLAG_CODES[state["run_flag"]] == "running"


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
