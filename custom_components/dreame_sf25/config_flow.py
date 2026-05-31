"""Config flow for Dreame SF25 Food Composter integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .dreame_cloud import AuthenticationException, DreameCloudClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_COUNTRY, default="DE"): str,
    }
)


class DreameSF25ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Dreame SF25."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: DreameCloudClient | None = None
        self._devices: list[dict] = []
        self._username: str = ""
        self._password: str = ""
        self._country: str = "DE"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: ask for Mi Home credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._country = user_input[CONF_COUNTRY]

            client = DreameCloudClient(self._username, self._password, self._country)

            try:
                await self.hass.async_add_executor_job(client.login)
                self._client = client
                self._devices = await self.hass.async_add_executor_job(client.get_devices)
            except AuthenticationException:
                errors["base"] = "invalid_auth"
            except Exception as ex:
                _LOGGER.error("Login exception: %s", ex)
                errors["base"] = "cannot_connect"
            else:
                if self._devices:
                    return await self.async_step_select_device()
                errors["base"] = "no_devices_found"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "app_url": "https://home.mi.com"
            },
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: pick the SF25 from the device list."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            device = next((d for d in self._devices if str(d["did"]) == device_id), None)

            if device:
                await self.async_set_unique_id(str(device["did"]))
                self._abort_if_unique_id_configured()

                name = (
                    device.get("customName")
                    or device.get("deviceInfo", {}).get("displayName")
                    or f"Dreame SF25 ({device_id})"
                )
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_COUNTRY: self._country,
                        CONF_DEVICE_ID: str(device["did"]),
                    },
                )
            errors["base"] = "device_not_found"

        device_options = {
            str(d["did"]): (
                f"{d.get('customName') or d.get('deviceInfo', {}).get('displayName', 'Unknown')}"
                f" — {d.get('model', '?')}"
            )
            for d in self._devices
        }

        if not device_options:
            return self.async_abort(reason="no_devices_found")

        schema = vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(device_options)})

        return self.async_show_form(
            step_id="select_device",
            data_schema=schema,
            errors=errors,
        )
