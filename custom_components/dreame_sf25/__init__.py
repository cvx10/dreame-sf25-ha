"""Dreame SF25 Food Composter integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

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
        # Typical after a warranty replacement: the new unit has a different
        # did. Reconfigure the entry (Settings > Devices & services > Dreame
        # SF25 > Reconfigure) to point it at the device now on the account.
        raise ConfigEntryNotReady(
            f"Device {device_id} not found on account "
            f"({len(devices)} device(s) available). If the composter was "
            f"replaced, reconfigure this entry to select the new one."
        )

    coordinator = DreameSF25Coordinator(hass=hass, client=client, device=device)

    try:
        await coordinator.async_setup()
    except Exception as ex:
        raise ConfigEntryNotReady(f"Failed to start MQTT: {ex}") from ex

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    _async_purge_stale_devices(hass, entry, str(device_id))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: DreameSF25Coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unloaded


def _async_purge_stale_devices(
    hass: HomeAssistant, entry: ConfigEntry, device_id: str
) -> None:
    """Reconcile the device registry after a device swap.

    Entities are keyed on the entry_id but the device is keyed on the did, so
    reconfiguring onto a replacement unit leaves a device entry that no longer
    matches. Where possible the old device entry is *renamed* onto the new did
    rather than dropped: that keeps its registry id, and with it the area, the
    user-chosen name and the labels — all of which a delete/recreate would
    silently lose. Anything still stale afterwards is detached from the entry.
    """
    registry = dr.async_get(hass)
    current = (DOMAIN, device_id)

    stale = [
        device
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if any(identifier[0] == DOMAIN for identifier in device.identifiers)
        and current not in device.identifiers
    ]
    if not stale:
        return

    # Only adopt the old entry when there is exactly one candidate and the new
    # did has no device of its own yet; anything else is ambiguous.
    if len(stale) == 1 and registry.async_get_device(identifiers={current}) is None:
        device = stale[0]
        _LOGGER.debug(
            "Migrating device %s from %s to %s", device.id, device.identifiers, current
        )
        registry.async_update_device(device.id, new_identifiers={current})
        return

    for device in stale:
        _LOGGER.debug("Removing stale device %s (%s)", device.name, device.identifiers)
        registry.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
