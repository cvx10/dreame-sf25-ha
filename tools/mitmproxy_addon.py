#!/usr/bin/env python3
"""
mitmproxy addon — capture DreameHome app traffic for the SF25.

Use this if the SF25 is NOT in Mi Home (DreameHome-only device).
Run via:  mitmproxy -s tools/mitmproxy_addon.py --listen-port 8080

Then configure your phone's WiFi proxy to point at your computer's IP:8080,
install the mitmproxy CA cert on the phone, and open the DreameHome app.

This addon will log all DreameHome API calls and extract:
  - Device IDs
  - Auth tokens
  - MIoT property reads/writes
"""
from __future__ import annotations

import json
import re
from mitmproxy import http


DREAME_HOSTS = {
    "eu.iot.dreame.tech",
    "cn.iot.dreame.tech",
    "us.iot.dreame.tech",
    "sg.iot.dreame.tech",
    "api.io.mi.com",
    "de.api.io.mi.com",
}

INTERESTING_PATHS = [
    "/dreame-auth/oauth/token",
    "/dreame-user-iot/iotuserbind/device/listV2",
    "/dreame-iot-com",
    "/miotspec/prop/get",
    "/miotspec/prop/set",
    "/miotspec/action",
    "/v2/home/rpc",
    "/home/device_list",
]

captured: list[dict] = []


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host
    path = flow.request.path

    if not any(h in host for h in DREAME_HOSTS):
        return

    interesting = any(p in path for p in INTERESTING_PATHS)
    if not interesting:
        return

    entry = {
        "host": host,
        "path": path,
        "method": flow.request.method,
        "request_headers": dict(flow.request.headers),
        "request_body": _try_parse(flow.request.get_text()),
        "status": flow.response.status_code if flow.response else None,
        "response_body": _try_parse(flow.response.get_text()) if flow.response else None,
    }

    captured.append(entry)

    print(f"\n{'='*60}")
    print(f"  {flow.request.method} {host}{path}")
    print(f"{'='*60}")

    # Highlight auth tokens
    req_body = entry["request_body"]
    if isinstance(req_body, dict):
        if "access_token" in req_body or "token" in str(req_body):
            print(f"  [AUTH] Token found in request!")
        _extract_device_ids(req_body)

    # Highlight MIoT properties in response
    resp_body = entry["response_body"]
    if isinstance(resp_body, dict):
        _extract_miot_props(resp_body)

    print(f"  Request:  {json.dumps(req_body, indent=2)[:500]}")
    print(f"  Response: {json.dumps(resp_body, indent=2)[:500]}")

    # Save running log
    with open("dreame_traffic.json", "w") as f:
        json.dump(captured, f, indent=2, default=str)


def _try_parse(text: str | None) -> dict | str | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text[:1000]


def _extract_device_ids(data: dict | str) -> None:
    text = json.dumps(data)
    dids = re.findall(r'"did"\s*:\s*"?(\d+)"?', text)
    if dids:
        print(f"  [DEVICE IDs] {dids}")


def _extract_miot_props(data: dict | str) -> None:
    text = json.dumps(data)
    props = re.findall(r'"siid"\s*:\s*(\d+).*?"piid"\s*:\s*(\d+)', text)
    if props:
        print(f"  [MIoT props] siid/piid pairs: {props[:10]}")
