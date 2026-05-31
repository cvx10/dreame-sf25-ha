#!/usr/bin/env python3
"""
Dreame SF25 — DreameHome device finder.

Lists all devices on your DreameHome account with their DID (device ID),
which is required to configure the Home Assistant integration.

Usage:
    .venv/bin/python3 tools/token_extractor.py
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import types

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
    print("DreameHome Device Finder")
    print("-" * 50)
    print("Use your DreameHome app credentials (email + password).")
    print()

    username = input("Email: ").strip()
    password = getpass.getpass("Password: ")
    country = input("Country code [DE]: ").strip().upper() or "DE"

    print("\nLogging in to DreameHome…")
    client = DreameCloudClient(username, password, country)

    try:
        client.login()
    except AuthenticationException as ex:
        print(f"Login failed: {ex}")
        sys.exit(1)

    print("Login successful!\n")

    print("Fetching device list…")
    devices = client.get_devices()

    if not devices:
        print("No devices found.")
        sys.exit(1)

    print(f"\nFound {len(devices)} device(s):\n")
    print(f"{'#':>3}  {'Name':30s} {'Model':30s} {'DID'}")
    print("-" * 80)

    for i, dev in enumerate(devices):
        name = dev.get("customName") or dev.get("deviceInfo", {}).get("displayName", "Unknown")
        model = dev.get("model", "?")
        did = dev.get("did", "?")
        print(f"[{i:>2}]  {name:30s} {model:30s} {did}")

    output = os.path.join(_root, "all_devices.json")
    with open(output, "w") as f:
        json.dump(devices, f, indent=2, default=str)
    print(f"\nFull device list saved to: all_devices.json")
    print("\nCopy your SF25's DID — you'll need it for discover.py and HA setup.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
