"""Dreame SF25 Food Composter integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)
from .coordinator import DreameSF25Coordinator
from .dreame_cloud import AuthenticationException, DreameCloudClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dreame SF25 from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    country = entry.data[CONF_COUNTRY]
    device_id = entry.data[CONF_DEVICE_ID]

    client = DreameCloudClient(username=username, password=password, country=country)

    try:
        await hass.async_add_executor_job(client.login)
    except AuthenticationException as ex:
        raise ConfigEntryAuthFailed(f"Invalid DreameHome credentials: {ex}") from ex
    except Exception as ex:
        raise ConfigEntryNotReady(f"Failed to connect to DreameHome cloud: {ex}") from ex

    # Locate the device record (needed for bindDomain/model).
    try:
        devices = await hass.async_add_executor_job(client.get_devices)
    except Exception as ex:
        raise ConfigEntryNotReady(f"Failed to fetch device list: {ex}") from ex

    device = next((d for d in devices if str(d.get("did")) == str(device_id)), None)
    if device is None:
        raise ConfigEntryNotReady(f"Device {device_id} not found on account")

    coordinator = DreameSF25Coordinator(hass=hass, client=client, device=device)

    try:
        await coordinator.async_setup()
    except Exception as ex:
        raise ConfigEntryNotReady(f"Failed to start MQTT: {ex}") from ex

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: DreameSF25Coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unloaded
