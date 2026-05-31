"""MQTT listener for the Dreame SF25.

The SF25 (dreame.fwd.u2527) does not answer HTTP get_properties (error 80001).
Instead it pushes `properties_changed` messages over the DreameHome MQTT broker.
This module connects to that broker and forwards property updates to a callback.

MQTT details (reverse-engineered, confirmed by sniffing):
  broker   : <bindDomain>, e.g. 10000.mt.eu.iot.dreame.tech:19973 (TLS, no verify)
  username : the account uid (from the login response)
  password : the OAuth access_token
  topic    : /status/{did}/{uid}/{model}/eu/
  payload  : {"data": {"method": "properties_changed",
                        "params": [{"siid": S, "piid": P, "value": V, "did": D}, ...]}}
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import threading
from typing import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

# Callback receives a list of (siid, piid, value) tuples.
PropertiesCallback = Callable[[list[tuple[int, int, object]]], None]


class DreameMqttClient:
    """Connects to the DreameHome MQTT broker and forwards property updates."""

    def __init__(
        self,
        bind_domain: str,
        uid: str,
        access_token: str,
        did: str,
        model: str,
        on_properties: PropertiesCallback,
        on_connection_change: Callable[[bool], None] | None = None,
    ) -> None:
        host, _, port = bind_domain.partition(":")
        self._host = host
        self._port = int(port) if port else 19973
        self._uid = uid
        self._token = access_token
        self._did = str(did)
        self._model = model
        self._on_properties = on_properties
        self._on_connection_change = on_connection_change

        self._topic = f"/status/{self._did}/{self._uid}/{self._model}/eu/"
        self._client: mqtt.Client | None = None
        self._connected = False
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def update_token(self, access_token: str) -> None:
        """Update the access token (call after a token refresh) and reconnect."""
        self._token = access_token
        if self._client:
            self._client.username_pw_set(username=self._uid, password=self._token)

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create the client and start the network loop in a background thread."""
        client_id = "p_" + os.urandom(8).hex()
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        client.username_pw_set(username=self._uid, password=self._token)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.reconnect_delay_set(min_delay=5, max_delay=120)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._client = client
        _LOGGER.debug("Connecting to MQTT %s:%s", self._host, self._port)
        client.connect_async(self._host, self._port, keepalive=30)
        client.loop_start()

    def stop(self) -> None:
        """Stop the network loop and disconnect."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
        self._connected = False

    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            self._connected = True
            client.subscribe(self._topic)
            # Wildcard catches any additional topics this device may use.
            client.subscribe(f"/status/{self._did}/#")
            _LOGGER.info("MQTT connected, subscribed to %s", self._topic)
            if self._on_connection_change:
                self._on_connection_change(True)
        else:
            self._connected = False
            _LOGGER.warning(
                "MQTT connect failed rc=%s (4=bad credentials, 5=not authorized)", rc
            )

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        _LOGGER.warning("MQTT disconnected rc=%s — will auto-reconnect", rc)
        if self._on_connection_change:
            self._on_connection_change(False)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            _LOGGER.debug("Non-JSON MQTT message on %s (%d bytes)", msg.topic, len(msg.payload))
            return

        data = payload.get("data", {})
        if data.get("method") != "properties_changed":
            _LOGGER.debug("Ignoring MQTT method=%s", data.get("method"))
            return

        params = data.get("params", [])
        updates: list[tuple[int, int, object]] = []
        for p in params:
            siid = p.get("siid")
            piid = p.get("piid")
            if siid is None or piid is None:
                continue
            updates.append((siid, piid, p.get("value")))

        if updates:
            _LOGGER.debug("MQTT properties_changed: %s", updates)
            try:
                self._on_properties(updates)
            except Exception:
                _LOGGER.exception("Error in properties callback")
