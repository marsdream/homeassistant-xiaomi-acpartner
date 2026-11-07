"""Async wrapper around the legacy MiIO protocol used by lumi.acpartner.v2.

The Xiaomi Air Conditioning Companion (first generation) predates the MIoT
platform: the device speaks the older MiIO JSON-RPC protocol over UDP 54321.
Its radio, ringtone and infrared capabilities are only reachable through these
legacy methods — the vendor never published a MIoT spec for the model, so the
official Home Assistant integration can only expose the air conditioning
properties.

All calls are read-only by default; mutating methods are called explicitly by
the entity layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from miio import Device

from .const import (
    DEFAULT_IR_SLOT,
    METHOD_CHANNELS,
    METHOD_DELETE_USER_MUSIC,
    METHOD_DOWNLOAD_PROGRESS,
    METHOD_DOWNLOAD_USER_MUSIC,
    METHOD_FM_PLAY,
    METHOD_FM_PLAY_SPECIFY,
    METHOD_FM_STATUS,
    METHOD_FM_VOLUME,
    METHOD_IR_LEARN_RESULT,
    METHOD_IR_LEARN_START,
    METHOD_IR_LEARN_STOP,
    METHOD_MUSIC_INFO,
    METHOD_MUSIC_SPACE,
    METHOD_PLAY_MUSIC,
    METHOD_PLAY_MUSIC_NEW,
    METHOD_SEND_CMD,
    METHOD_SEND_IR_CODE,
    METHOD_STATUS,
    RINGTONE_TYPES,
    USER_MUSIC_ID,
)

_LOGGER = logging.getLogger(__name__)


class XiaomiAcCompanionError(Exception):
    """Raised when the device rejects or does not answer a MiIO call."""


class XiaomiAcCompanion:
    """Talk to one lumi.acpartner.v2 over the local network.

    The device is addressed directly; no Xiaomi account or cloud round trip is
    involved, which is why this keeps working years after the model was
    discontinued.
    """

    def __init__(self, host: str, token: str) -> None:
        """Initialise the client for a device."""
        self._host = host
        self._token = token
        self._device: Device | None = None
        self._lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Return the device IP address."""
        return self._host

    def _get_device(self) -> Device:
        """Return (and cache) the miio device handle."""
        if self._device is None:
            # lazy_discover=False skips the mDNS/LAN discovery round trip; the
            # device answers on its well-known UDP port 54321 directly.
            self._device = Device(self._host, self._token, lazy_discover=False)
        return self._device

    async def async_call(self, method: str, params: Any = None) -> Any:
        """Call a MiIO method and return its result.

        The miio library is not consistent about what ``Device.send`` returns:
        depending on the method and the installed version it may hand back the
        value directly or a coroutine. Normalise both here.
        """
        # The miio protocol implementation is not thread safe and blocks on
        # UDP round trips, so keep the calls serialised and off the event loop.
        async with self._lock:
            return await asyncio.to_thread(self._call_sync, method, params)

    def _call_sync(self, method: str, params: Any) -> Any:
        """Perform one MiIO call, blocking."""
        device = self._get_device()
        try:
            result = device.send(method, params)
        except Exception as err:  # noqa: BLE001 - surfaced as a typed error
            raise XiaomiAcCompanionError(f"{method} failed: {err}") from err

        if asyncio.iscoroutine(result) or hasattr(result, "__await__"):
            try:
                result = _run_sync(result)
            except Exception as err:  # noqa: BLE001
                raise XiaomiAcCompanionError(f"{method} failed: {err}") from err
        return result

    # ------------------------------------------------------------------
    # Read-only helpers
    # ------------------------------------------------------------------
    async def async_status(self) -> dict[str, Any]:
        """Return the air conditioning state (model, state string, load)."""
        result = await self.async_call(METHOD_STATUS, [])
        if not result or len(result) < 3:
            raise XiaomiAcCompanionError("unexpected get_model_and_state reply")
        return {
            "model": result[0],
            "state": result[1],
            "load_power": result[2],
        }

    async def async_radio_status(self) -> dict[str, Any]:
        """Return the current radio state."""
        result = await self.async_call(METHOD_FM_STATUS, [])
        if not isinstance(result, dict):
            raise XiaomiAcCompanionError("unexpected get_prop_fm reply")
        return result

    async def async_channels(self) -> list[dict[str, Any]]:
        """Return the list of favourite radio stations.

        The device pages the list ten entries at a time; ``get_channels``
        stops returning a ``chs`` key once the end is reached.
        """
        channels: list[dict[str, Any]] = []
        start = 0
        while True:
            result = await self.async_call(METHOD_CHANNELS, {"start": start})
            if not isinstance(result, dict):
                break
            page = result.get("chs") or []
            if not page:
                break
            for entry in page:
                if "id" in entry:
                    channels.append(entry)
            start += 10
            if start > 500:
                break
        return channels

    async def async_music_free_space(self) -> int:
        """Return the free space for user uploaded audio, in bytes."""
        result = await self.async_call(METHOD_MUSIC_SPACE, [])
        if isinstance(result, (list, tuple)) and result:
            return int(result[0])
        return 0

    async def async_ringtones(self, kind: str) -> list[dict[str, Any]]:
        """Return the ringtone list of one category.

        ``kind`` is one of ``alarm``, ``clock``, ``chord`` or ``custom``.
        """
        type_id = RINGTONE_TYPES.get(kind)
        if type_id is None:
            raise XiaomiAcCompanionError(f"unknown ringtone category {kind}")
        result = await self.async_call(METHOD_MUSIC_INFO, [type_id])
        if isinstance(result, dict):
            return list(result.get("list") or [])
        return []

    # ------------------------------------------------------------------
    # Radio
    # ------------------------------------------------------------------
    async def async_radio_on(self) -> None:
        """Start or resume radio playback."""
        await self.async_call(METHOD_FM_PLAY, ["on"])

    async def async_radio_off(self) -> None:
        """Stop radio playback."""
        await self.async_call(METHOD_FM_PLAY, ["off"])

    async def async_play_station(self, program_id: int) -> None:
        """Play a specific station by its program id."""
        await self.async_call(METHOD_FM_PLAY_SPECIFY, {"id": int(program_id), "type": 0})

    async def async_set_volume(self, volume: int) -> None:
        """Set the radio volume (0-100)."""
        await self.async_call(METHOD_FM_VOLUME, [str(int(volume))])

    # ------------------------------------------------------------------
    # Ringtones and user audio
    # ------------------------------------------------------------------
    async def async_play_ringtone(self, ringtone_id: int, volume: int | None = None) -> None:
        """Play a ringtone by its mid."""
        if volume is None:
            await self.async_call(METHOD_PLAY_MUSIC, [int(ringtone_id)])
        else:
            await self.async_call(METHOD_PLAY_MUSIC_NEW, [str(int(ringtone_id)), int(volume)])

    async def async_download_user_music(self, url: str, slot: int = USER_MUSIC_ID) -> None:
        """Make the device fetch an audio file over HTTP and store it."""
        await self.async_call(METHOD_DELETE_USER_MUSIC, [str(slot)])
        await self.async_call(METHOD_DOWNLOAD_USER_MUSIC, [str(slot), url])

    async def async_delete_user_music(self, slot: int = USER_MUSIC_ID) -> None:
        """Remove a previously uploaded audio file."""
        await self.async_call(METHOD_DELETE_USER_MUSIC, [str(slot)])

    async def async_download_progress(self) -> tuple[str, int]:
        """Return the slot and the progress of the running download.

        The device answers with ``"<slot>:<percentage>"``, e.g. ``99999:100``.
        """
        result = await self.async_call(METHOD_DOWNLOAD_PROGRESS, [])
        if isinstance(result, (list, tuple)) and result:
            result = result[0]
        text = str(result)
        slot, _, percent = text.partition(":")
        if percent.isdigit():
            return slot, int(percent)
        return text, 0

    async def async_play_user_music(self, volume: int | None = None) -> None:
        """Play the audio file previously uploaded to the user slot."""
        if volume is None:
            await self.async_call(METHOD_PLAY_MUSIC, [USER_MUSIC_ID])
        else:
            await self.async_call(METHOD_PLAY_MUSIC_NEW, [str(USER_MUSIC_ID), int(volume)])

    # ------------------------------------------------------------------
    # Infrared
    # ------------------------------------------------------------------
    async def async_ir_learn_start(self, slot: int = DEFAULT_IR_SLOT) -> None:
        """Start learning an infrared command into a storage slot."""
        await self.async_call(METHOD_IR_LEARN_START, [int(slot)])

    async def async_ir_learn_stop(self, slot: int = DEFAULT_IR_SLOT) -> None:
        """Stop learning."""
        await self.async_call(METHOD_IR_LEARN_STOP, [int(slot)])

    async def async_ir_learn_result(self) -> Any:
        """Return the last learned infrared command."""
        return await self.async_call(METHOD_IR_LEARN_RESULT, [])

    async def async_send_ir_code(self, code: str) -> None:
        """Send a raw air conditioning command string."""
        await self.async_call(METHOD_SEND_CMD, [str(code)])

    async def async_send_learned_ir_code(self, model: str, code: str, slot: int = 0) -> None:
        """Send a learned infrared command.

        The device does not accept the model and the payload separately: it
        expects one binary blob that merges the model header with the learned
        payload and appends a checksum. The layout is the one used by the
        original ``python-miio`` implementation.
        """
        try:
            model_bytes = bytes.fromhex(model)
            code_bytes = bytes.fromhex(code)
        except ValueError as err:
            raise XiaomiAcCompanionError(
                "model and code must be hexadecimal strings"
            ) from err

        if not 0 <= slot <= 134:
            raise XiaomiAcCompanionError(f"invalid IR slot: {slot}")

        slot_bytes = bytes([121 + slot])

        command_bytes = (
            code_bytes[0:1]
            + model_bytes[2:8]
            + b"\x94\x70\x1F\xFF"
            + slot_bytes
            + b"\xFF"
            + code_bytes[13:16]
            + b"\x27"
        )
        checksum = sum(command_bytes) & 0xFF
        command_bytes = command_bytes + bytes([checksum]) + code_bytes[18:]

        await self.async_call(METHOD_SEND_IR_CODE, [command_bytes.hex().upper()])


def _run_sync(awaitable: Any) -> Any:
    """Resolve an awaitable from synchronous code.

    The miio coroutines have to be driven by an event loop; this helper is only
    used on the worker thread, where no loop is running.
    """
    return asyncio.run(_await(awaitable))


async def _await(awaitable: Any) -> Any:
    """Await a single awaitable."""
    return await awaitable

