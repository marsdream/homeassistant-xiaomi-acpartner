"""The Xiaomi Air Conditioning Companion integration.

Supports the first generation ``lumi.acpartner.v2`` (and its v1/v3 siblings),
which expose a network radio, ringtone engine, infrared learning and custom
audio upload over the legacy MiIO protocol — none of which is reachable
through the vendor's official MIoT integration.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_NAME,
    CONF_TOKEN,
    CONF_TTS_API_KEY,
    CONF_TTS_API_URL,
    CONF_TTS_BASE_URL,
    DOMAIN,
    USER_MUSIC_ID,
)
from .coordinator import XiaomiAcCompanionCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    host = entry.data["host"]
    token = entry.data[CONF_TOKEN]

    # One shared coordinator for both platforms: the device is single core and
    # every MiIO call interrupts whatever it is playing, so it must not be
    # polled twice.
    coordinator = XiaomiAcCompanionCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "device": coordinator.device,
        "name": coordinator.name,
        "tts_api_key": entry.options.get(CONF_TTS_API_KEY, ""),
        "tts_api_url": entry.options.get(CONF_TTS_API_URL, ""),
        "tts_base_url": entry.options.get(CONF_TTS_BASE_URL, ""),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass, entry)

    # The device has about 11 MB of storage. Remove an upload that was left
    # behind by an interrupted run, otherwise it would stay there forever.
    hass.async_create_task(_async_cleanup_orphan(hass, coordinator.device))
    return True


async def _async_cleanup_orphan(hass: HomeAssistant, device) -> None:
    """Delete a leftover upload from a previous run."""
    try:
        await device.async_delete_user_music(USER_MUSIC_ID)
    except Exception as err:  # noqa: BLE001 - a cleanup must never break setup
        _LOGGER.debug("Could not clean up the device storage: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


def get_device_info(entry: ConfigEntry, name: str) -> DeviceInfo:
    """Build the device registry entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=name,
        manufacturer="Xiaomi",
        model="lumi.acpartner.v2",
        configuration_url=f"http://{entry.data['host']}",
    )
