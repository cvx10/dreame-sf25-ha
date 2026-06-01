#!/usr/bin/env python3
"""
Dreame SF25 — MQTT property sniffer.

The SF25 (dreame.fwd.u2527) does NOT respond to HTTP get_properties relay
(error 80001). Instead, it PUSHES state changes in real time over MQTT.

This tool connects to the DreameHome MQTT broker and listens for
`properties_changed` messages. Every time you physically interact with the
device (press a button, start/stop a cycle, open the lid), the device
publishes the changed (siid, piid, value) tuples — which is exactly the
property map we need.

Usage:
    .venv/bin/python3 tools/mqtt_sniffer.py

Then go physically interact with your SF25:
  - Press the power button
  - Start / pause / stop a cycle
  - Open and close the lid
  - Change the mode
  - Watch the values stream in here, and note what each one corresponds to.

Press Ctrl+C to stop and save the captured property map.
"""
from __future__ import annotations

import getpass
import json
import os
import ssl
import sys
import types
from collections import defaultdict
from datetime import datetime

# Register stub packages so Python skips HA-dependent __init__.py
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)

_pkg = types.ModuleType("custom_components")
_subpkg = types.ModuleType("custom_components.dreame_sf25")
_subpkg.__path__ = [os.path.join(_root, "custom_components", "dreame_sf25")]
_subpkg.__package__ = "custom_components.dreame_sf25"
sys.modules.setdefault("custom_components", _pkg)
sys.modules["custom_components.dreame_sf25"] = _subpkg

import paho.mqtt.client as mqtt

from custom_components.dreame_sf25.dreame_cloud import DreameCloudClient, AuthenticationException


# Track all (siid, piid) -> set of observed values
observed: dict[tuple[int, int], list] = defaultdict(list)
message_log: list[dict] = []


def main() -> None:
    print("=" * 64)
    print("  Dreame SF25 — MQTT Property Sniffer")
    print("=" * 64)
    print()

    username = os.environ.get("DREAME_USER") or input("DreameHome email: ").strip()

    # Password resolution order: env var, password file (robust against shell
    # special chars), then interactive prompt. DREAME_PASS_FILE is read raw and
    # only trailing newlines are stripped (passwords may contain spaces).
    password = os.environ.get("DREAME_PASS")
    if not password:
        pass_file = os.environ.get("DREAME_PASS_FILE")
        if pass_file and os.path.exists(pass_file):
            with open(pass_file, "r") as f:
                password = f.read().rstrip("\r\n")
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Password: ")
        else:
            print("ERROR: no password. Set DREAME_PASS or DREAME_PASS_FILE.")
            sys.exit(2)

    country = (os.environ.get("DREAME_COUNTRY") or "DE").upper()
    if not os.environ.get("DREAME_COUNTRY") and sys.stdin.isatty():
        country = (input("Country code [DE]: ").strip().upper() or "DE")

    print("\nLogging in…")
    client = DreameCloudClient(username, password, country)
    try:
        client.login()
    except AuthenticationException as ex:
        print(f"Login failed: {ex}")
        sys.exit(1)

    uid = client.uid
    token = client.access_token
    print(f"Logged in. uid={uid}")

    if not uid:
        print("\nWARNING: No 'uid' in login response. Dumping full session to inspect:")
        print(json.dumps(client._session_data, indent=2, default=str))
        print("\nLooking for the user id in another field…")

    # --- Get device ---
    devices_file = os.path.join(_root, "all_devices.json")
    if os.path.exists(devices_file):
        with open(devices_file) as f:
            devices = json.load(f)
    else:
        devices = client.get_devices()

    if not devices:
        print("No devices found.")
        sys.exit(1)

    device = devices[0]
    did = str(device["did"])
    model = device["model"]
    # Fall back to masterUid if login didn't return uid
    if not uid:
        uid = device.get("masterUid")
        print(f"Falling back to device masterUid: {uid}")

    print(f"Device: {device.get('customName')} ({model}, did={did})")

    bind_domain = device.get("bindDomain") or "10000.mt.eu.iot.dreame.tech:19973"
    host, port = bind_domain.split(":")
    port = int(port)

    # Topic the device publishes status to
    topic = f"/status/{did}/{uid}/{model}/eu/"
    print(f"\nMQTT broker: mqtts://{host}:{port}")
    print(f"Subscribing to: {topic}")
    print()

    # --- MQTT client ---
    client_id = "p_" + os.urandom(8).hex()
    # paho-mqtt 2.x requires explicit callback API version; VERSION1 keeps the
    # classic on_connect(c, userdata, flags, rc) / on_message(c, userdata, msg) signatures.
    try:
        mqttc = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
    except (AttributeError, TypeError):
        # paho-mqtt 1.x fallback
        mqttc = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    mqttc.username_pw_set(username=uid, password=token)

    # TLS without cert verification (matches the app behaviour)
    mqttc.tls_set(cert_reqs=ssl.CERT_NONE)
    mqttc.tls_insecure_set(True)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            print(">>> Connected to MQTT broker!")
            # Subscribe to the specific status topic AND a wildcard to catch everything
            c.subscribe(topic)
            c.subscribe(f"/status/{did}/#")
            c.subscribe(f"#")  # catch-all to discover any topic the device uses
            print(">>> Subscribed. Now go interact with your SF25!")
            print(">>> Press buttons, start a cycle, open the lid…")
            print(">>> Values will appear below. Ctrl+C when done.\n")
        else:
            print(f">>> MQTT connection failed with code {rc}")
            print("    rc=1: wrong protocol | rc=4: bad user/pass | rc=5: not authorized")

    def on_message(c, userdata, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            print(f"[{ts}] {msg.topic}: <non-JSON {len(msg.payload)} bytes> {msg.payload[:80]!r}")
            return

        message_log.append({"ts": ts, "topic": msg.topic, "payload": payload})

        data = payload.get("data", {})
        method = data.get("method", "?")
        params = data.get("params", [])

        if method == "properties_changed" and isinstance(params, list):
            print(f"[{ts}] properties_changed:")
            for p in params:
                siid = p.get("siid")
                piid = p.get("piid")
                value = p.get("value")
                key = (siid, piid)
                if value not in observed[key]:
                    observed[key].append(value)
                vstr = json.dumps(value) if isinstance(value, (dict, list)) else repr(value)
                if len(vstr) > 60:
                    vstr = vstr[:60] + "…"
                print(f"         siid={siid:>2} piid={piid:>2}  value={vstr}")
        else:
            print(f"[{ts}] {msg.topic} method={method}: {json.dumps(params)[:120]}")

        _save()

    mqttc.on_connect = on_connect
    mqttc.on_message = on_message

    try:
        mqttc.connect(host, port, keepalive=30)
    except Exception as ex:
        print(f"Failed to connect: {ex}")
        sys.exit(1)

    try:
        mqttc.loop_forever()
    except KeyboardInterrupt:
        print("\n\nStopping…")
        mqttc.disconnect()
        _print_summary()


def _save() -> None:
    out = {
        "observed_properties": {
            f"{siid}_{piid}": {"siid": siid, "piid": piid, "values_seen": vals}
            for (siid, piid), vals in observed.items()
        },
        "message_log": message_log[-200:],  # keep last 200
    }
    with open(os.path.join(_root, "mqtt_capture.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)


def _print_summary() -> None:
    print("\n" + "=" * 64)
    print("  Discovered properties")
    print("=" * 64)
    if not observed:
        print("\nNo properties_changed messages captured.")
        print("Make sure you physically interacted with the device while listening.")
        return

    print(f"\n{'siid':>5} {'piid':>5}  values observed")
    print("-" * 64)
    for (siid, piid), vals in sorted(observed.items()):
        vstr = ", ".join(repr(v)[:20] for v in vals[:5])
        print(f"  {siid:>3}   {piid:>3}   {vstr}")

    print("\n" + "=" * 64)
    print("  PROPERTY_MAPPING snippet for const.py")
    print("=" * 64 + "\n")
    print("PROPERTY_MAPPING: Final[dict[str, dict[str, int]]] = {")
    for (siid, piid), vals in sorted(observed.items()):
        print(f'    "prop_{siid}_{piid}": {{"siid": {siid}, "piid": {piid}}},  # seen: {vals[:3]}')
    print("}")
    print("\nFull capture saved to mqtt_capture.json")


if __name__ == "__main__":
    main()
