#!/usr/bin/env python3
"""
Dreame SF25 — DreameHome property discovery tool.

Logs in to DreameHome, lists devices, then brute-forces all MIoT
properties (siid 1–N, piid 1–N) to discover what the SF25 exposes.
Prints a PROPERTY_MAPPING snippet ready to paste into const.py.

Usage:
    .venv/bin/python3 tools/discover.py
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import types
from typing import Any

# Register stub packages so Python skips HA-dependent __init__.py
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)

_pkg = types.ModuleType("custom_components")
_subpkg = types.ModuleType("custom_components.dreame_sf25")
_subpkg.__path__ = [os.path.join(_root, "custom_components", "dreame_sf25")]
_subpkg.__package__ = "custom_components.dreame_sf25"
sys.modules.setdefault("custom_components", _pkg)
sys.modules["custom_components.dreame_sf25"] = _subpkg

from custom_components.dreame_sf25.dreame_cloud import DreameCloudClient, AuthenticationException


def main() -> None:
    print("=" * 60)
    print("  Dreame SF25 — Property Discovery Tool (DreameHome)")
    print("=" * 60)
    print()

    # Support env vars for non-interactive use
    username = os.environ.get("DREAME_USER") or input("DreameHome email: ").strip()
    password = os.environ.get("DREAME_PASS") or getpass.getpass("Password: ")
    country = (os.environ.get("DREAME_COUNTRY") or input("Country code [DE]: ").strip().upper() or "DE")

    print("\nLogging in…")
    client = DreameCloudClient(username, password, country)
    try:
        client.login()
    except AuthenticationException as ex:
        print(f"Login failed: {ex}")
        sys.exit(1)
    print("Logged in successfully.\n")

    # --- Device selection ---
    # If all_devices.json exists from a previous token_extractor run, use it
    devices_file = os.path.join(_root, "all_devices.json")
    if os.path.exists(devices_file):
        with open(devices_file) as f:
            devices = json.load(f)
        print(f"Using {len(devices)} device(s) from all_devices.json")
    else:
        devices = client.get_devices()

    if not devices:
        print("No devices found on this account.")
        sys.exit(1)

    print(f"\nFound {len(devices)} device(s):\n")
    for i, dev in enumerate(devices):
        name = dev.get("customName") or dev.get("deviceInfo", {}).get("displayName", "Unknown")
        model = dev.get("model", "?")
        did = dev.get("did", "?")
        print(f"  [{i}] {name:30s} model={model:30s} did={did}")

    print()
    # Pre-select index 0 automatically if there's only one device
    if len(devices) == 1:
        idx = 0
        print("Auto-selected the only device.")
    else:
        idx_str = input("Select device index [0]: ").strip()
        idx = int(idx_str) if idx_str.isdigit() else 0

    device = devices[idx]
    did = str(device["did"])
    name = device.get("customName") or device.get("deviceInfo", {}).get("displayName", "?")
    print(f"\nSelected: {name} (did={did}, model={device.get('model')})")

    _save_json("device_info.json", device)
    print("Device info saved to device_info.json\n")

    # --- Property probe ---
    # Wider range by default since no public spec exists for dreame.fwd.u2527
    max_siid = int(os.environ.get("MAX_SIID") or input("Max siid to scan [10]: ").strip() or "10")
    max_piid = int(os.environ.get("MAX_PIID") or input("Max piid to scan [30]: ").strip() or "30")

    total = max_siid * max_piid
    print(f"\nScanning {total} property combinations (siid 1–{max_siid}, piid 1–{max_piid})…")
    print("Tip: dreame.fwd.u2527 has no public MIoT spec — this scan discovers all properties.")
    print("This may take 1–3 minutes (batches of 50 with 0.3s pause). Please wait…\n")

    results = client.probe_all_properties(did, max_siid=max_siid, max_piid=max_piid)

    # --- Print results ---
    print("\n" + "=" * 60)
    print("  Property scan results")
    print("=" * 60)
    print(f"{'siid':>5} {'piid':>5}  {'status':>8}  value")
    print("-" * 60)

    accessible: list[tuple[int, int, Any]] = []
    for (siid, piid), result in sorted(results.items()):
        code = result.get("code", -1)
        value = result.get("value")
        if code == 0:
            marker = "✓ OK"
            accessible.append((siid, piid, value))
            print(f"  siid={siid:2d}  piid={piid:2d}  {marker:>8}  value={value!r}")

    print(f"\n{len(accessible)} readable properties found out of {total} tested.\n")

    if not accessible:
        print("No readable properties found.")
        print()
        print("Most likely cause: the SF25 is in SLEEP MODE between cycles.")
        print("The DreameHome cloud can't reach the device when it's not active.")
        print()
        print("To fix:")
        print("  1. Press the physical POWER button on the SF25")
        print("     (or start a composting cycle)")
        print("  2. Wait 5–10 seconds for it to reconnect to the cloud")
        print("  3. Run this script again immediately")
        print()
        print("The device shows as online on the local network (ping works)")
        print("but its MQTT connection to DreameHome is inactive when sleeping.")
        sys.exit(1)

    # --- Generate const.py snippet ---
    print("=" * 60)
    print("  Paste into custom_components/dreame_sf25/const.py")
    print("  Replace the PROPERTY_MAPPING section:")
    print("=" * 60)
    print()
    print("PROPERTY_MAPPING: Final[dict[str, dict[str, int]]] = {")
    for siid, piid, value in accessible:
        print(f'    "prop_{siid}_{piid}": {{"siid": {siid}, "piid": {piid}}},  # current value: {value!r}')
    print("}")
    print()

    # Save full results
    _save_json("probe_results.json", {
        "device": device,
        "accessible_properties": [
            {"siid": s, "piid": p, "value": v} for s, p, v in accessible
        ],
        "all_results": {
            f"{s}_{p}": r for (s, p), r in results.items()
        },
    })
    print("Full results saved to probe_results.json")


def _save_json(filename: str, data: Any) -> None:
    path = os.path.join(_root, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
