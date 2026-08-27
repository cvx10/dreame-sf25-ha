"""DreameHome cloud API client.

Implements authentication and MIoT device control via the DreameHome cloud
(eu.iot.dreame.tech), as used by the DreameHome mobile app.

Protocol reverse-engineered from:
  - TA2k/ioBroker.dreame (JavaScript implementation)
  - Tasshack/dreame-vacuum (for MIoT property format)
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DreameHome cloud constants (EU region)
# ---------------------------------------------------------------------------
_DOMAIN = "eu.iot.dreame.tech:13267"
_AUTH_URL = f"https://{_DOMAIN}/dreame-auth/oauth/token"
_DEVICE_LIST_URL = f"https://{_DOMAIN}/dreame-user-iot/iotuserbind/device/listV2"
_COMMAND_URL = f"https://{_DOMAIN}/dreame-iot-com-10000/device/sendCommand"
_REFRESH_URL = f"https://{_DOMAIN}/dreame-auth/oauth/token"

# App credentials (from public ioBroker.dreame reverse-engineering)
_AUTHORIZATION = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="

# Constant salt used for password hashing
_PASSWORD_SALT = "RAylYC%fmSKp7%Tq"

# Static dreame-rlc header (AES-128-ECB of "eu|en|DE" with key "EETjszu*XI5znHsI")
_RLC_HEADER = "7787607c258cdd79141ec1866eb5476c"

# Maximum MIoT properties the cloud will accept in a single get_properties call.
# Measured against a dreame.fwd.u2527 on 2026-08-27: 16 succeeds, 17 and above
# come back as code 80001 — the same code the cloud uses for an unreachable
# device, which makes an oversized request look exactly like a sleeping one.
_MAX_PROPERTIES_PER_REQUEST = 16


def _hash_password(password: str) -> str:
    """MD5 hash of password + salt, as required by DreameHome auth."""
    return hashlib.md5((password + _PASSWORD_SALT).encode()).hexdigest()


def _make_headers(access_token: str | None = None) -> dict[str, str]:
    headers = {
        "user-agent": "Dart/3.2 (dart:io)",
        "dreame-meta": "cv=i_829",
        "dreame-rlc": _RLC_HEADER,
        "tenant-id": "000000",
        "host": _DOMAIN,
        "authorization": _AUTHORIZATION,
        "content-type": "application/json",
    }
    if access_token:
        headers["dreame-auth"] = f"bearer {access_token}"
    else:
        headers["dreame-auth"] = "bearer"
    return headers


class DreameCloudException(Exception):
    """Base exception for DreameHome API errors."""


class AuthenticationException(DreameCloudException):
    """Raised on login failure."""


class DreameCloudClient:
    """DreameHome cloud client for MIoT device control."""

    def __init__(
        self,
        username: str,
        password: str,
        country: str = "de",
    ) -> None:
        self._username = username
        self._password = password
        self._country = country.upper()  # API expects "DE", "FR", etc.
        self._session = requests.Session()

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_in: int = 0
        self._token_time: float = 0.0
        self._logged_in: bool = False
        self._uid: str | None = None  # User ID from login (needed for MQTT)
        self._session_data: dict = {}  # Full login response
        # DID spellings the account has rejected outright (code 80002); see
        # _send_command. Cached per client so a wrong form is tried only once.
        self._bad_did_forms: set[str] = set()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Log in to DreameHome. Returns True on success."""
        try:
            resp = self._session.post(
                _AUTH_URL,
                headers={**_make_headers(), "content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "password",
                    "scope": "all",
                    "platform": "IOS",
                    "type": "account",
                    "username": self._username,
                    "password": _hash_password(self._password),
                    "country": self._country,
                    "lang": self._country.lower(),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            _LOGGER.debug("DreameHome login response: %s", data)
        except requests.HTTPError as ex:
            _LOGGER.error("DreameHome login HTTP error %s: %s", ex.response.status_code, ex.response.text)
            raise AuthenticationException(f"HTTP {ex.response.status_code}") from ex
        except Exception as ex:
            _LOGGER.error("DreameHome login failed: %s", ex)
            raise AuthenticationException(str(ex)) from ex

        if "access_token" not in data:
            _LOGGER.error("DreameHome login: no access_token. Response: %s", data)
            raise AuthenticationException(f"No access_token in response: {data}")

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._expires_in = data.get("expires_in", 3600)
        self._uid = str(data.get("uid")) if data.get("uid") is not None else None
        self._session_data = data
        self._token_time = time.time()
        self._logged_in = True
        _LOGGER.info("DreameHome login successful (uid=%s)", self._uid)
        return True

    @property
    def uid(self) -> str | None:
        """User ID, needed as the MQTT username."""
        return self._uid

    @property
    def access_token(self) -> str | None:
        """Access token, needed as the MQTT password."""
        return self._access_token

    def refresh_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            return self.login()
        try:
            resp = self._session.post(
                _REFRESH_URL,
                headers={**_make_headers(), "content-type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if "access_token" in data:
                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                self._expires_in = data.get("expires_in", 3600)
                self._token_time = time.time()
                return True
        except Exception as ex:
            _LOGGER.warning("Token refresh failed, re-logging: %s", ex)
        return self.login()

    def _ensure_token(self) -> None:
        """Re-authenticate if the token is about to expire."""
        if not self._logged_in:
            self.login()
            return
        elapsed = time.time() - self._token_time
        if elapsed > (self._expires_in - 120):
            self.refresh_token()

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def get_devices(self) -> list[dict]:
        """Return all devices on the DreameHome account."""
        self._ensure_token()
        try:
            resp = self._session.post(
                _DEVICE_LIST_URL,
                headers=_make_headers(self._access_token),
                json={
                    "sharedStatus": 1,
                    "current": 1,
                    "size": 100,
                    "lang": self._country.lower(),
                    "timestamp": int(time.time() * 1000),
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            _LOGGER.debug("Device list: %s", data)
        except Exception as ex:
            _LOGGER.error("Failed to get device list: %s", ex)
            return []

        if data.get("code") != 0:
            _LOGGER.error("Device list error: %s", data)
            return []

        return data.get("data", {}).get("page", {}).get("records", [])

    def find_device(self, ip: str | None = None, mac: str | None = None) -> dict | None:
        """Find a device by local IP or MAC address."""
        for dev in self.get_devices():
            prop = {}
            try:
                prop = json.loads(dev.get("property", "{}"))
            except Exception:
                pass
            if ip and prop.get("localip") == ip:
                return dev
            if mac:
                dev_mac = dev.get("mac", "").lower().replace(":", "")
                if dev_mac == mac.lower().replace(":", ""):
                    return dev
        return None

    # ------------------------------------------------------------------
    # MIoT commands via DreameHome cloud
    # ------------------------------------------------------------------

    def _send_command(self, did: str, method: str, params: Any, retry: int = 2) -> Any:
        """Send a MIoT command via DreameHome sendCommand endpoint."""
        self._ensure_token()

        # Some devices store DID as signed int32; try both forms if one fails.
        did_variants = [did]
        try:
            int_did = int(did)
            if int_did < 0:
                did_variants.append(str(int_did & 0xFFFFFFFF))  # unsigned 32-bit
            elif int_did > 0x7FFFFFFF:
                did_variants.append(str(int_did - 0x100000000))  # signed 32-bit
        except ValueError:
            pass

        remaining = [d for d in did_variants if d not in self._bad_did_forms]
        # Never leave ourselves with nothing to try.
        did_variants = remaining or did_variants[:1]

        for attempt in range(retry + 1):
            for d in did_variants:
                request_id = random.randint(1000, 9999)
                payload = {
                    "did": d,
                    "id": request_id,
                    "data": {
                        "did": d,
                        "id": request_id,
                        "method": method,
                        "params": params,
                        "from": "XXXXXX",
                    },
                }
                try:
                    resp = self._session.post(
                        _COMMAND_URL,
                        headers=_make_headers(self._access_token),
                        json=payload,
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    _LOGGER.debug("sendCommand response (did=%s): %s", d, data)
                except Exception as ex:
                    _LOGGER.debug("sendCommand exception (did=%s attempt=%d): %s", d, attempt, ex)
                    continue

                if data.get("code") == 0:
                    return data.get("data")

                code = data.get("code")
                if code == 80001:
                    # The cloud reuses 80001 for two unrelated situations: the
                    # device is asleep and did not answer, or the request itself
                    # was refused for being too large (see
                    # _MAX_PROPERTIES_PER_REQUEST). Do not assume the first.
                    _LOGGER.warning(
                        "No answer from the device (code 80001, did=%s attempt=%d/%d). "
                        "Either the SF25 is asleep — press its physical power button — "
                        "or the request exceeded %d properties.",
                        d, attempt + 1, retry + 1, _MAX_PROPERTIES_PER_REQUEST,
                    )
                elif code == 80002:
                    # "user device authorization error": this DID form is not the
                    # one the account is bound to. Retrying it only adds latency
                    # and log noise, so drop it for the rest of the session.
                    _LOGGER.debug(
                        "DID form %s rejected by the account (code 80002), dropping it", d
                    )
                    self._bad_did_forms.add(d)
                else:
                    _LOGGER.warning("sendCommand error code %s (did=%s): %s", code, d, data)
                # Try next DID variant before giving up
        return None

    def get_properties(self, did: str, properties: list[dict[str, int]]) -> list[dict]:
        """
        Read MIoT properties.

        properties: list of {"siid": X, "piid": Y}
        Returns list of {"siid": X, "piid": Y, "value": V, "code": 0}
        """
        collected: list[dict] = []
        for i in range(0, len(properties), _MAX_PROPERTIES_PER_REQUEST):
            chunk = properties[i : i + _MAX_PROPERTIES_PER_REQUEST]
            params = [{"did": did, "siid": p["siid"], "piid": p["piid"]} for p in chunk]
            result = self._send_command(did, "get_properties", params)
            if result and "result" in result:
                collected.extend(result["result"])
        return collected

    def set_property(self, did: str, siid: int, piid: int, value: Any) -> bool:
        """Write a single MIoT property. Returns True on success."""
        params = [{"did": did, "siid": siid, "piid": piid, "value": value}]
        result = self._send_command(did, "set_properties", params)
        if result and "result" in result:
            results = result["result"]
            return bool(results and results[0].get("code") == 0)
        return False

    def call_action(self, did: str, siid: int, aiid: int, params: list | None = None) -> Any:
        """Invoke a MIoT action."""
        payload = {"did": did, "siid": siid, "aiid": aiid, "in": params or []}
        result = self._send_command(did, "action", payload)
        if result and "result" in result:
            return result["result"]
        return None

    def probe_all_properties(self, did: str, max_siid: int = 10, max_piid: int = 20) -> dict:
        """
        Brute-force scan all (siid, piid) combinations to discover device properties.
        Requests are split by get_properties() into chunks the cloud accepts.
        Returns dict keyed by (siid, piid) with {"value": V, "code": C}.
        """
        all_props = [
            {"siid": siid, "piid": piid}
            for siid in range(1, max_siid + 1)
            for piid in range(1, max_piid + 1)
        ]

        results: dict[tuple[int, int], dict] = {}
        batch_size = _MAX_PROPERTIES_PER_REQUEST

        for i in range(0, len(all_props), batch_size):
            chunk = all_props[i : i + batch_size]
            raw = self.get_properties(did, chunk)
            for item in raw:
                siid = item.get("siid")
                piid = item.get("piid")
                results[(siid, piid)] = {
                    "value": item.get("value"),
                    "code": item.get("code", -1),
                }
            # Brief pause to avoid rate limiting
            time.sleep(0.3)

        return results
