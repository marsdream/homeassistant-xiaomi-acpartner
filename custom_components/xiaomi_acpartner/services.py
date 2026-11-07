"""Services for the Xiaomi Air Conditioning Companion integration.

Besides the radio and the infrared remote — both exposed as standard
entities — the device can play ringtones and fetch arbitrary audio files over
HTTP into its own storage. That last one is what makes text to speech and
custom recordings possible: the device downloads the file itself, so no
streaming server has to stay up while it plays.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import pathlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    PLAYBACK_MARGIN,
    DOMAIN,
    MAX_UPLOAD_BYTES,
    MIN_FREE_SPACE,
    TTS_DEFAULT_SPEAKER,
    USER_MUSIC_ID,
)
from .tts import async_check_space, async_render_aac, public_url

_LOGGER = logging.getLogger(__name__)

ATTR_RINGTONE_ID = "ringtone_id"
ATTR_VOLUME = "volume"
ATTR_URL = "url"
ATTR_MESSAGE = "message"
ATTR_CATEGORY = "category"
ATTR_API_KEY = "api_key"
ATTR_SPEAKER = "speaker"

SERVICE_PLAY_RINGTONE = "play_ringtone"
SERVICE_SPEAK = "speak"
SERVICE_CLEANUP_AUDIO = "cleanup_audio"
SERVICE_PLAY_USER_AUDIO = "play_user_audio"
SERVICE_UPLOAD_AUDIO = "upload_audio"

PLAY_RINGTONE_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Required(ATTR_RINGTONE_ID): cv.positive_int,
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    }
)

PLAY_USER_AUDIO_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    }
)

UPLOAD_AUDIO_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Required(ATTR_URL): cv.url,
    }
)

CLEANUP_AUDIO_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
    }
)

SPEAK_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_API_KEY): cv.string,
        vol.Optional(ATTR_SPEAKER): cv.string,
    }
)


async def _devices_for(hass: HomeAssistant, call: ServiceCall) -> list[Any]:
    """Return the device clients targeted by a service call."""
    entries = hass.data.get(DOMAIN, {})
    entity_ids = call.data.get("entity_id")
    clients: list[Any] = []
    for entry_id, data in entries.items():
        name = data["name"]
        if entity_ids:
            # Match on the friendly name of the entities belonging to this entry.
            matched = False
            for suffix in (" 收音机", " 红外"):
                if f"media_player.{_slugify(name + suffix)}" in entity_ids:
                    matched = True
                if f"remote.{_slugify(name + suffix)}" in entity_ids:
                    matched = True
            if not matched:
                continue
        clients.append(data["device"])
    return clients


def _slugify(text: str) -> str:
    """Return the entity id slug of a name."""
    from homeassistant.util import slugify

    return slugify(text)


async def async_setup_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the integration services once."""

    async def _play_ringtone(call: ServiceCall) -> None:
        """Play a built-in ringtone."""
        ringtone_id = call.data[ATTR_RINGTONE_ID]
        volume = call.data.get(ATTR_VOLUME)
        for device in await _devices_for(hass, call):
            await device.async_play_ringtone(ringtone_id, volume)

    async def _play_user_audio(call: ServiceCall) -> None:
        """Play the audio file previously uploaded to the device."""
        volume = call.data.get(ATTR_VOLUME)
        for device in await _devices_for(hass, call):
            await device.async_play_user_music(volume)

    async def _upload_audio(call: ServiceCall) -> None:
        """Make the device download an audio file over HTTP.

        The device keeps the file as-is in its own storage, so the size of the
        upload directly reduces the free space. Check the size first and keep a
        safety margin so the device never runs out of room.
        """
        url = call.data[ATTR_URL]
        for device in await _devices_for(hass, call):
            size = await _remote_size(hass, url)
            if size is None:
                _LOGGER.warning("Could not determine the size of %s", url)
            elif size > MAX_UPLOAD_BYTES:
                raise ServiceValidationError(
                    f"The file is {size} bytes, which is larger than the "
                    f"{MAX_UPLOAD_BYTES} byte limit for this device"
                )

            free = await device.async_music_free_space()
            if free is not None:
                if size and free - size < MIN_FREE_SPACE:
                    raise ServiceValidationError(
                        f"Not enough space on the device: {free} bytes free, "
                        f"{size} bytes needed, {MIN_FREE_SPACE} bytes reserved"
                    )

            # Replace the previous upload so the space is reclaimed first.
            await device.async_delete_user_music(USER_MUSIC_ID)
            await device.async_download_user_music(url, USER_MUSIC_ID)
            percent = await _wait_for_download(hass, device)
            if percent < 100:
                raise ServiceValidationError(
                    "The device did not finish downloading the file in time"
                )

    if not hass.services.has_service(DOMAIN, SERVICE_PLAY_RINGTONE):
        hass.services.async_register(
            DOMAIN, SERVICE_PLAY_RINGTONE, _play_ringtone, schema=PLAY_RINGTONE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_PLAY_USER_AUDIO):
        hass.services.async_register(
            DOMAIN, SERVICE_PLAY_USER_AUDIO, _play_user_audio, schema=PLAY_USER_AUDIO_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_UPLOAD_AUDIO):
        hass.services.async_register(
            DOMAIN, SERVICE_UPLOAD_AUDIO, _upload_audio, schema=UPLOAD_AUDIO_SCHEMA
        )


    async def _speak(call: ServiceCall) -> None:
        """Render a short text and play it on the device.

        The device only has around 11 MB of free storage, so the audio is
        rendered at a modest bitrate and the result is removed again once it
        has been played.
        """
        message = call.data[ATTR_MESSAGE]
        volume = call.data.get(ATTR_VOLUME)
        api_key = call.data.get(ATTR_API_KEY) or _configured_key(hass)
        api_url = _configured_api_url(hass)
        speaker = call.data.get(ATTR_SPEAKER) or TTS_DEFAULT_SPEAKER
        base_url = _base_url(hass)
        for device in await _devices_for(hass, call):
            rendered = await async_render_aac(
                hass, message, api_key, speaker=speaker, api_url=api_url
            )
            if not rendered:
                raise ServiceValidationError("Could not render the text to speech")
            path, size, seconds = rendered
            # The length is measured locally: the number the device reports
            # for the uploaded file is not reliable.
            if not seconds:
                seconds = 8
            await async_check_space(device, size)
            url = public_url(base_url, path)
            try:
                await device.async_download_user_music(url, USER_MUSIC_ID)
                percent = await _wait_for_download(hass, device)
                if percent < 100:
                    raise ServiceValidationError(
                        "The device did not finish downloading the audio in time"
                    )
                await device.async_play_user_music(volume)
                # The device reads the file from its storage while it plays.
                # Deleting it right away would cut the audio off, so wait for
                # the playback to finish before the space is freed again.
                await _wait_for_playback(device, seconds)
            finally:
                # Free the space again, the device is tiny.
                await device.async_delete_user_music(USER_MUSIC_ID)

    if not hass.services.has_service(DOMAIN, SERVICE_SPEAK):
        hass.services.async_register(
            DOMAIN, SERVICE_SPEAK, _speak, schema=SPEAK_SCHEMA
        )


    async def _cleanup_audio(call: ServiceCall) -> None:
        """Remove the uploaded audio files from the device.

        The device has about 11 MB of storage, so a file that was uploaded for
        a single announcement should not stay there forever.
        """
        for device in await _devices_for(hass, call):
            await device.async_delete_user_music(USER_MUSIC_ID)

    if not hass.services.has_service(DOMAIN, SERVICE_CLEANUP_AUDIO):
        hass.services.async_register(
            DOMAIN, SERVICE_CLEANUP_AUDIO, _cleanup_audio, schema=CLEANUP_AUDIO_SCHEMA
        )


async def _wait_for_download(
    hass: HomeAssistant, device: Any, timeout: int = 120
) -> int:
    """Wait until the device finished downloading the uploaded audio.

    The device reports the progress as ``"<slot>:<percentage>"``.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        slot, percent = await device.async_download_progress()
        if percent >= 100:
            return percent
        await asyncio.sleep(1)
    _LOGGER.warning("The download did not finish within %s seconds", timeout)
    return 0


async def _remote_size(hass: HomeAssistant, url: str) -> int | None:
    """Return the content length of a URL, or None when it is unknown."""
    import aiohttp

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.head(url, allow_redirects=True) as response:
                length = response.headers.get("Content-Length")
                return int(length) if length else None
    except Exception as err:  # noqa: BLE001 - any failure means "unknown"
        _LOGGER.debug("Could not read the size of %s: %s", url, err)
        return None


def _base_url(hass: HomeAssistant) -> str:
    """Return the URL the device can reach Home Assistant on.

    Home Assistant often reports an address that only works inside its own
    container network. The device sits in the normal home network, so the
    address has to be one it can actually reach.
    """
    for data in hass.data.get(DOMAIN, {}).values():
        configured = data.get("tts_base_url")
        if configured:
            return str(configured)

    try:
        from homeassistant.helpers.network import get_url

        url = get_url(hass, allow_internal=True, allow_external=True)
    except Exception:  # noqa: BLE001 - fall back to the internal address
        url = f"http://{hass.config.api.host}:{hass.config.api.port}"

    # An address inside the container network is useless for the device.
    if ".139." in url or "172.1" in url or "172.2" in url:
        _LOGGER.warning(
            "Home Assistant reports %s, which the device probably cannot "
            "reach. Set the tts_base_url option to an address in your home "
            "network.",
            url,
        )
    return url


def _configured_key(hass: HomeAssistant) -> str:
    """Return the text to speech key from the config entry options."""
    for data in hass.data.get(DOMAIN, {}).values():
        key = data.get("tts_api_key")
        if key:
            return str(key)
    return ""


def _configured_api_url(hass: HomeAssistant) -> str:
    """Return the address of the fallback text to speech service."""
    for data in hass.data.get(DOMAIN, {}).values():
        url = data.get("tts_api_url")
        if url:
            return str(url)
    return ""


async def _wait_for_playback(device: Any, fallback: int = 8) -> None:
    """Wait until the device finished playing the uploaded audio.

    The device keeps the audio in its own storage while it plays, so the file
    may only be removed after the playback is over. The length of the file is
    read *before* the playback starts: asking the device while it plays
    interrupts the audio stream, which truncates the last syllable.
    """
    await asyncio.sleep(max(fallback, 1) + PLAYBACK_MARGIN)



