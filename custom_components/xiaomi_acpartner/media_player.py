"""Media player entity for the Xiaomi Air Conditioning Companion radio."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_device_info
from .const import DOMAIN
from .coordinator import XiaomiAcCompanionCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the radio entity."""
    coordinator: XiaomiAcCompanionCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([XiaomiAcCompanionRadio(coordinator, entry)])


class XiaomiAcCompanionRadio(CoordinatorEntity[XiaomiAcCompanionCoordinator], MediaPlayerEntity):
    """Expose the built-in network radio as a media player."""

    _attr_should_poll = False

    def __init__(
        self, coordinator: XiaomiAcCompanionCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialise the radio."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"{coordinator.name} 收音机"
        self._attr_unique_id = f"{entry.entry_id}-radio"
        self._attr_device_info = get_device_info(entry, coordinator.name)
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
        )
        self._attr_source = None
        cached_volume = coordinator.last_radio.get("current_volume")
        self._attr_volume_level = (
            min(max(int(cached_volume) / 100.0, 0.0), 1.0) if cached_volume else 0.0
        )
        self._attr_is_volume_muted = False

    @property
    def available(self) -> bool:
        """Return whether the device is reachable."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state.

        Read from the cached radio state: while the radio plays the device is
        never queried, so the cache is the only truth available.
        """
        radio = self.coordinator.last_radio or {}
        if radio.get("current_status") == "run":
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        """Return the name of the current station."""
        radio = self.coordinator.last_radio or {}
        program = radio.get("current_program")
        if program is None:
            return None
        return f"电台 {program}"

    @property
    def source(self) -> str | None:
        """Return the currently selected source."""
        return self._attr_source

    @property
    def source_list(self) -> list[str]:
        """Return the list of favourite stations."""
        return [
            str(channel.get("id"))
            for channel in self.coordinator.channels
        ]

    @property
    def volume_level(self) -> float:
        """Return the volume as a 0.0-1.0 fraction."""
        radio = self.coordinator.last_radio or {}
        volume = radio.get("current_volume")
        if volume is not None:
            return min(max(float(volume) / 100.0, 0.0), 1.0)
        return self._attr_volume_level

    @property
    def is_volume_muted(self) -> bool:
        """Return whether the radio is muted."""
        radio = self.coordinator.last_radio or {}
        if radio.get("current_volume") is not None:
            return int(radio["current_volume"]) == 0
        return self._attr_is_volume_muted

    async def async_media_play(self) -> None:
        """Start the radio."""
        await self.coordinator.device.async_radio_on()
        self.coordinator.set_playing(True)
        self._write_state()

    async def async_media_pause(self) -> None:
        """Pause the radio."""
        await self.coordinator.device.async_radio_off()
        self.coordinator.set_playing(False)
        # The radio stopped, the device can be queried again.
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop the radio."""
        await self.coordinator.device.async_radio_off()
        self.coordinator.set_playing(False)
        # The radio stopped, the device can be queried again.
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn the radio on."""
        await self.async_media_play()

    async def async_turn_off(self) -> None:
        """Turn the radio off."""
        await self.async_media_stop()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the radio volume."""
        level = int(round(volume * 100))
        await self.coordinator.device.async_set_volume(level)
        self._attr_volume_level = volume
        self._write_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the radio."""
        level = 0 if mute else int(round(self.volume_level * 100))
        await self.coordinator.device.async_set_volume(level)
        self._attr_is_volume_muted = mute
        self._write_state()

    async def async_select_source(self, source: str) -> None:
        """Play a favourite station."""
        await self.coordinator.device.async_play_station(int(source))
        self._attr_source = source
        radio = dict(self.coordinator.last_radio or {})
        radio["current_program"] = int(source)
        self.coordinator.set_last_radio(radio)
        self._write_state()

    def _write_state(self) -> None:
        """Push the locally known state without polling the device.

        The radio is playing at this point, so asking the device would
        interrupt the audio.
        """
        radio = dict(self.coordinator.last_radio or {})
        radio["current_status"] = "run"
        volume = self._attr_volume_level
        if not volume and radio.get("current_volume"):
            # Fall back to the volume the device last reported.
            volume = int(radio["current_volume"]) / 100.0
            self._attr_volume_level = volume
        radio["current_volume"] = int(round(volume * 100))
        self.coordinator.set_last_radio(radio)
        self.async_write_ha_state()
