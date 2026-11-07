"""Data coordinator for the Xiaomi Air Conditioning Companion integration.

The first generation air conditioning companion is a very small device with a
single core. Every MiIO call it has to decrypt and answer interrupts the
audio stream it is playing, so the coordinator polls only the cheap radio
status and refreshes the expensive lists (stations, free space, ringtones)
rarely.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_NAME, DOMAIN, SCAN_INTERVAL, SLOW_REFRESH_INTERVAL
from .device import XiaomiAcCompanion

_LOGGER = logging.getLogger(__name__)


class XiaomiAcCompanionCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the device for radio state, station list and free space."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{entry.entry_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self.name: str = entry.data.get(CONF_NAME) or f"空调伴侣 {entry.data['host']}"
        self.device = XiaomiAcCompanion(entry.data["host"], entry.data["token"])
        self._slow_data: dict[str, Any] = {}
        self._last_slow_refresh = 0.0
        self._last_radio: dict[str, Any] = {}
        self._playing = False
        self._known_playing = False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current state from the device.

        While the radio is playing the device is left completely alone: every
        MiIO request interrupts the audio stream, so even a single status
        poll is audible as a stutter. The cached state is reused instead and
        refreshed only once the radio has been stopped.
        """
        data: dict[str, Any] = {}

        if self._playing:
            # The radio is running: do not touch the device at all.
            data.update(self._slow_data)
            data["radio"] = self._last_radio
            return data

        radio = await self.device.async_radio_status()
        self._last_radio = radio
        data["radio"] = radio

        # The station list is needed to populate the entity, so the first
        # refresh always fetches it. After that the expensive calls are
        # refreshed only every few minutes.
        now = time.monotonic()
        if (
            not self._slow_data
            or now - self._last_slow_refresh >= SLOW_REFRESH_INTERVAL
        ):
            self._last_slow_refresh = now
            await self._async_refresh_slow()

        data.update(self._slow_data)

        # Learn whether the device is playing, then stay quiet until the user
        # stops it. Without this the very first poll after a restart would
        # interrupt a radio that is already running.
        if not self._known_playing:
            self._known_playing = True
            self._playing = radio.get("current_status") == "run"

        return data

    def set_playing(self, playing: bool) -> None:
        """Record whether the radio is currently playing.

        The device answers ``get_prop_fm`` with ``current_status``, but asking
        it is exactly what causes the stutter, so the state is tracked from
        the actions the integration performed instead.
        """
        self._playing = playing
        radio = dict(self._last_radio)
        radio["current_status"] = "run" if playing else "pause"
        self._last_radio = radio

    def set_last_radio(self, radio: dict[str, Any]) -> None:
        """Update the cached radio state without polling the device."""
        self._last_radio = radio

    @property
    def last_radio(self) -> dict[str, Any]:
        """Return the cached radio state."""
        return self._last_radio

    @property
    def channels(self) -> list[dict[str, Any]]:
        """Return the cached list of favourite stations."""
        return self._slow_data.get("channels") or []

    async def _async_refresh_slow(self) -> None:
        """Refresh the station list, free space and custom ringtones."""
        try:
            self._slow_data["channels"] = await self.device.async_channels()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read channels: %s", err)
            self._slow_data.setdefault("channels", [])

        try:
            self._slow_data["free_space"] = await self.device.async_music_free_space()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read music free space: %s", err)
            self._slow_data.setdefault("free_space", 0)

        try:
            self._slow_data["ringtones"] = await self.device.async_ringtones("custom")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read custom ringtones: %s", err)
            self._slow_data.setdefault("ringtones", [])

        try:
            self._slow_data["ir_learn_result"] = await self.device.async_ir_learn_result()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not read IR learn result: %s", err)
            self._slow_data.setdefault("ir_learn_result", None)
