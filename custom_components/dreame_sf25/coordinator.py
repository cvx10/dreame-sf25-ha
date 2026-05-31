"""Push-based coordinator for the Dreame SF25.

The SF25 only communicates via MQTT push (no working HTTP property read).
This coordinator:
  1. Logs in to DreameHome (to obtain uid + access_token)
  2. Opens an MQTT connection to the device's broker
  3. Updates HA entities whenever a `properties_changed` message arrives

It subclasses DataUpdateCoordinator with no polling interval; updates are pushed
via async_set_updated_data() from the MQTT callback thread.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, PROPERTY_MAPPING
from .dreame_cloud import DreameCloudClient
from .mqtt_client import DreameMqttClient

_LOGGER = logging.getLogger(__name__)

# Reverse lookup: (siid, piid) -> property key
_REVERSE_MAPPING = {(v["siid"], v["piid"]): k for k, v in PROPERTY_MAPPING.items()}


class DreameSF25Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holds the latest SF25 state, fed by MQTT push messages."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: DreameCloudClient,
        device: dict,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device['did']}",
            update_interval=None,  # push-based; no polling
        )
        self._client = client
        self._device = device
        self._did = str(device["did"])
        self.device_name = (
            device.get("customName")
            or device.get("deviceInfo", {}).get("displayName")
            or "Dreame SF25"
        )
        self.model_id = device.get("model", "dreame.fwd.u2527")
        self._mqtt: DreameMqttClient | None = None
        # Start with an empty state; values fill in as MQTT messages arrive.
        self.data = {}

    async def async_setup(self) -> None:
        """Start the MQTT connection."""
        uid = self._client.uid
        token = self._client.access_token
        bind_domain = self._device.get("bindDomain") or "10000.mt.eu.iot.dreame.tech:19973"

        if not uid or not token:
            raise RuntimeError("Missing uid/access_token after login")

        self._mqtt = DreameMqttClient(
            bind_domain=bind_domain,
            uid=uid,
            access_token=token,
            did=self._did,
            model=self.model_id,
            on_properties=self._handle_properties,
            on_connection_change=self._handle_connection_change,
        )
        await self.hass.async_add_executor_job(self._mqtt.start)
        _LOGGER.info("SF25 MQTT coordinator started for %s", self.device_name)

    async def async_shutdown(self) -> None:
        """Stop the MQTT connection."""
        if self._mqtt:
            await self.hass.async_add_executor_job(self._mqtt.stop)
            self._mqtt = None

    # ------------------------------------------------------------------
    # MQTT callbacks (run in the paho network thread)
    # ------------------------------------------------------------------

    def _handle_properties(self, updates: list[tuple[int, int, Any]]) -> None:
        """Apply incoming property updates and notify HA (thread-safe)."""
        new_data = dict(self.data or {})
        changed = False
        for siid, piid, value in updates:
            key = _REVERSE_MAPPING.get((siid, piid))
            if key:
                new_data[key] = value
                changed = True
            else:
                _LOGGER.debug("Unmapped property siid=%s piid=%s value=%r", siid, piid, value)

        if changed:
            # Bounce onto the event loop thread.
            self.hass.loop.call_soon_threadsafe(self._async_apply_data, new_data)

    @callback
    def _async_apply_data(self, new_data: dict[str, Any]) -> None:
        self.async_set_updated_data(new_data)

    def _handle_connection_change(self, connected: bool) -> None:
        _LOGGER.debug("MQTT connection changed: connected=%s", connected)

    # ------------------------------------------------------------------
    # Control (best-effort, via DreameHome HTTP relay)
    # ------------------------------------------------------------------

    async def async_set_property(self, prop_key: str, value: Any) -> bool:
        """Attempt to set a property via the HTTP relay.

        NOTE: the device may reject this with error 80001 while asleep. Kept here
        for future control entities; sensor entities do not use it.
        """
        mapping = PROPERTY_MAPPING.get(prop_key)
        if not mapping:
            raise ValueError(f"Unknown property key: {prop_key}")
        return await self.hass.async_add_executor_job(
            self._client.set_property,
            self._did,
            mapping["siid"],
            mapping["piid"],
            value,
        )
