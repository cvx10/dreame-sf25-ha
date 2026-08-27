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

# On reconfigure the account is already known, so the password may be left
# blank to keep the stored one. Only the device selection usually changes.
STEP_RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD, default=""): str,
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

    async def _async_login_and_list(self) -> str | None:
        """Log in and fetch the account's device list.

        Returns None on success, or an error key for the form.
        """
        client = DreameCloudClient(self._username, self._password, self._country)

        try:
            await self.hass.async_add_executor_job(client.login)
            self._client = client
            self._devices = await self.hass.async_add_executor_job(client.get_devices)
        except AuthenticationException:
            return "invalid_auth"
        except Exception as ex:  # noqa: BLE001 - surfaced to the user as cannot_connect
            _LOGGER.error("Login exception: %s", ex)
            return "cannot_connect"

        if not self._devices:
            return "no_devices_found"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: ask for DreameHome credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._country = user_input[CONF_COUNTRY]

            error = await self._async_login_and_list()
            if error:
                errors["base"] = error
            else:
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "app_url": "https://home.mi.com"
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Re-point an existing entry at another device on the same account.

        Needed after a warranty replacement: the DreameHome `did` of the new
        unit differs from the old one, and the `did` lives in the entry data.
        Without this step the only fix is to delete and re-add the integration,
        which drops every entity and its history.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            # An empty password means "keep the stored one".
            self._password = user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]
            self._country = user_input[CONF_COUNTRY]

            error = await self._async_login_and_list()
            if error:
                errors["base"] = error
            else:
                return await self.async_step_select_device()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_RECONFIGURE_SCHEMA,
                {
                    CONF_USERNAME: entry.data[CONF_USERNAME],
                    CONF_COUNTRY: entry.data[CONF_COUNTRY],
                },
            ),
            errors=errors,
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: pick the SF25 from the device list.

        Shared by the initial setup and the reconfigure flow.
        """
        errors: dict[str, str] = {}
        reconfiguring = self.source == config_entries.SOURCE_RECONFIGURE

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            device = next((d for d in self._devices if str(d["did"]) == device_id), None)

            if device:
                name = (
                    device.get("customName")
                    or device.get("deviceInfo", {}).get("displayName")
                    or f"Dreame SF25 ({device_id})"
                )
                data = {
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_COUNTRY: self._country,
                    CONF_DEVICE_ID: str(device["did"]),
                }

                if reconfiguring:
                    # The did IS the unique_id, so it has to move with the
                    # entry data. _abort_if_unique_id_mismatch() is deliberately
                    # not used here: a changed did is the whole point.
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(),
                        data_updates=data,
                        unique_id=str(device["did"]),
                    )

                await self.async_set_unique_id(str(device["did"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data=data)
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
