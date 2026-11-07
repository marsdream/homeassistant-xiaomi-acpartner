"""Text to speech support for the Xiaomi Air Conditioning Companion.

The device can fetch an audio file over HTTP and play it, which makes it
possible to have it speak. The rendered file is written into the Home
Assistant ``www`` directory so the device can download it directly, and it is
removed again once it has been played.

The device stores the file as-is and only has about 11 MB of free space, so
the size of the rendering is checked before anything is uploaded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant

from .const import (
    MAX_UPLOAD_BYTES,
    MIN_FREE_SPACE,
    TTS_DEFAULT_SPEAKER,
    TTS_FOLDER,
    TTS_MAX_CHARS,
    TTS_MAX_CACHE_FILES,
    TTS_PIPELINE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


async def async_render(
    hass: HomeAssistant,
    message: str,
    api_key: str,
    speaker: str = TTS_DEFAULT_SPEAKER,
    api_url: str | None = None,
) -> tuple[str, int] | None:
    """Render text to speech and return the URL and the size of the file.

    The file is written into the Home Assistant ``www`` directory so that the
    device can download it over HTTP without any authentication.
    """
    message = message.strip()
    if len(message) > TTS_MAX_CHARS:
        raise ValueError(
            f"The message is {len(message)} characters long, the limit is "
            f"{TTS_MAX_CHARS}. Split it into smaller pieces."
        )

    folder = hass.config.path("www", TTS_FOLDER)
    await hass.async_add_executor_job(_ensure_folder, folder)

    name = hashlib.sha1(f"{speaker}:{message}".encode()).hexdigest()[:20] + ".mp3"
    target = f"{folder}/{name}"

    if await hass.async_add_executor_job(_size_of, target):
        # Already rendered, reuse it.
        return f"/local/{TTS_FOLDER}/{name}", await hass.async_add_executor_job(
            _size_of, target
        )

    payload = await _async_fetch(hass, message, api_key, speaker, api_url)
    if payload is None:
        return None

    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"The rendered audio is {len(payload)} bytes, which is over the "
            f"{MAX_UPLOAD_BYTES} byte limit of this device"
        )

    await hass.async_add_executor_job(_write_file, target, payload)
    return f"/local/{TTS_FOLDER}/{name}", len(payload)


async def async_render_aac(
    hass: HomeAssistant,
    message: str,
    api_key: str,
    speaker: str = TTS_DEFAULT_SPEAKER,
    api_url: str | None = None,
) -> tuple[str, int, int] | None:
    """Render text to speech and store it as an AAC file.

    The device only plays AAC files. An uploaded mp3 ends up in the device as
    an empty entry with a duration of zero and stays silent.
    """
    message = message.strip()
    if len(message) > TTS_MAX_CHARS:
        raise ValueError(
            f"The message is {len(message)} characters long, the limit is "
            f"{TTS_MAX_CHARS}. Split it into smaller pieces."
        )

    folder = hass.config.path("www", TTS_FOLDER)
    await hass.async_add_executor_job(_ensure_folder, folder)

    digest = hashlib.sha1(
        f"{TTS_PIPELINE_VERSION}:{speaker}:{message}".encode()
    ).hexdigest()[:20]
    mp3_name = f"{digest}.mp3"
    aac_name = f"{digest}.aac"
    mp3_path = f"{folder}/{mp3_name}"
    aac_path = f"{folder}/{aac_name}"

    size = await hass.async_add_executor_job(_size_of, aac_path)
    if size:
        # A cached file was reused. The cleanup still has to run, otherwise
        # the folder keeps growing every time a message is repeated.
        await hass.async_add_executor_job(_cleanup_folder, folder)
        seconds = await hass.async_add_executor_job(_duration_of_file, aac_path)
        return f"/local/{TTS_FOLDER}/{aac_name}", size, seconds

    payload = await _async_render_audio(hass, message, api_key, speaker, api_url)
    if payload is None:
        return None

    await hass.async_add_executor_job(_write_file, mp3_path, payload)
    converted = await hass.async_add_executor_job(_convert_to_aac, mp3_path, aac_path)
    if not converted:
        _LOGGER.error("Could not convert the rendered audio to AAC")
        return None

    size = await hass.async_add_executor_job(_size_of, aac_path)
    if size > MAX_UPLOAD_BYTES:
        _LOGGER.warning(
            "The rendered audio is %s bytes, which is over the limit of %s bytes",
            size,
            MAX_UPLOAD_BYTES,
        )
        await hass.async_add_executor_job(_remove_file, aac_path)
        raise ValueError(
            f"The rendered audio is {size} bytes, which is over the "
            f"{MAX_UPLOAD_BYTES} byte limit of this device"
        )

    await hass.async_add_executor_job(_remove_file, mp3_path)
    await hass.async_add_executor_job(_cleanup_folder, folder)
    seconds = await hass.async_add_executor_job(_duration_of_file, aac_path)
    return f"/local/{TTS_FOLDER}/{aac_name}", size, seconds


async def _async_render_audio(
    hass: HomeAssistant,
    message: str,
    api_key: str,
    speaker: str,
    api_url: str | None = None,
) -> bytes | None:
    """Render the message to an mp3.

    The Microsoft Edge voices are used when they are available, they are
    free and work without a key. The fallback is a hosted service that needs
    an API key.
    """
    payload = await _async_edge_tts(hass, message, speaker)
    if payload:
        return payload
    if api_key and api_url:
        return await _async_fetch(hass, message, api_key, speaker, api_url)
    if not api_key and not api_url:
        _LOGGER.error(
            "The Edge voices are not available and no fallback service is "
            "configured. Install edge-tts or set a text to speech service in "
            "the options of the integration."
        )
    return None


async def _async_edge_tts(
    hass: HomeAssistant, message: str, speaker: str
) -> bytes | None:
    """Render the message with the Microsoft Edge voices."""
    voice = _voice_for(speaker)
    try:
        return await hass.async_add_executor_job(_edge_tts_sync, message, voice)
    except Exception as err:  # noqa: BLE001 - the service may be unreachable
        _LOGGER.warning("Could not use the Edge voices: %s", err)
        return None


def _import_edge_tts():
    """Import the edge-tts package, ignoring a shadowing local folder.

    Home Assistant can have a custom integration called ``edge_tts`` in its
    config directory. When that directory ends up on the import path, the
    plain ``import edge_tts`` picks up the integration folder instead of the
    package and the module has no ``Communicate``. The package is loaded from
    its own location in that case.
    """
    import importlib
    import importlib.util

    module = importlib.import_module("edge_tts")
    if hasattr(module, "Communicate"):
        return module

    spec = importlib.util.find_spec("edge_tts")
    locations = list(getattr(spec, "submodule_search_locations", []) or [])
    if not locations:
        return module

    # Find the directory of the installed package, not a local folder that
    # happens to have the same name.
    for path in locations:
        init = os.path.join(path, "__init__.py")
        if os.path.isfile(init):
            spec = importlib.util.spec_from_file_location(
                "edge_tts_package", init, submodule_search_locations=[path]
            )
            if spec and spec.loader:
                loaded = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(loaded)
                if hasattr(loaded, "Communicate"):
                    return loaded
    return module


def _edge_tts_sync(message: str, voice: str) -> bytes | None:
    """Render the message with edge-tts, blocking."""
    import asyncio

    edge_tts = _import_edge_tts()

    async def _render() -> bytes:
        audio = b""
        communicate = edge_tts.Communicate(message, voice=voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio

    return asyncio.run(_render())


# A few short aliases for the most useful Chinese Edge voices, so that the
# voice can be picked without knowing the full Edge name. Any other value is
# passed to Edge as it is, so every available voice can be used.
VOICE_ALIASES = {
    "zh_female_qingxin": "zh-CN-XiaoxiaoNeural",
    "zh_female_sichuan": "zh-CN-XiaoyiNeural",
    "zh_male_xiaoming": "zh-CN-YunxiNeural",
    "zh_male_zhubo": "zh-CN-YunjianNeural",
    "zh_male_yunyang": "zh-CN-YunyangNeural",
}


def _voice_for(speaker: str) -> str:
    """Map a speaker name to an Edge voice."""
    return VOICE_ALIASES.get(speaker, speaker or TTS_DEFAULT_SPEAKER)


async def _async_fetch(
    hass: HomeAssistant,
    message: str,
    api_key: str,
    speaker: str,
    url: str | None = None,
) -> bytes | None:
    """Ask the text to speech service for the audio."""
    if not url:
        _LOGGER.error("No text to speech service configured")
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {"text": message, "speaker": speaker, "format": "mp3"}
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60)
        ) as session:
            async with session.post(
                url, headers=headers, json=body
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error(
                        "The text to speech service answered with %s: %s",
                        response.status,
                        text[:200],
                    )
                    return None
                return await response.read()
    except asyncio.TimeoutError:
        _LOGGER.error("The text to speech service timed out")
        return None
    except aiohttp.ClientError as err:
        _LOGGER.error("Could not reach the text to speech service: %s", err)
        return None


def _ensure_folder(folder: str) -> None:
    """Create the download folder."""
    import os

    os.makedirs(folder, exist_ok=True)


def _write_file(path: str, payload: bytes) -> None:
    """Write the rendered audio to disk."""
    with open(path, "wb") as handle:
        handle.write(payload)


def _size_of(path: str) -> int:
    """Return the size of a file, or zero when it does not exist."""
    import os

    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def public_url(base_url: str, path: str) -> str:
    """Build the absolute URL the device can download."""
    return f"{base_url.rstrip('/')}{path}"


async def async_check_space(device: Any, size: int) -> None:
    """Raise when the upload would eat too much of the device storage."""
    free = await device.async_music_free_space()
    if free is None:
        return
    if free - size < MIN_FREE_SPACE:
        raise ValueError(
            f"Not enough space on the device: {free} bytes free, {size} bytes "
            f"needed, {MIN_FREE_SPACE} bytes are kept free as a reserve"
        )


def _convert_to_aac(mp3_path: str, aac_path: str) -> bool:
    """Convert an mp3 file into the AAC format the device understands."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        _LOGGER.error("ffmpeg is not available, cannot convert the audio")
        return False

    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        mp3_path,
        # Pad the end with a bit of silence. The mp3 decoder delay makes the
        # encoder cut off the very last sample, which the device then plays
        # as a click instead of the final word.
        "-af",
        "apad=pad_dur=0.6",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-f",
        "adts",
        aac_path,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError) as err:
        _LOGGER.error("Could not run ffmpeg: %s", err)
        return False

    if result.returncode != 0:
        _LOGGER.error("ffmpeg failed: %s", result.stderr[:300])
        return False
    return _size_of(aac_path) > 0


def _duration_of_file(path: str) -> int:
    """Return the length of an audio file in seconds.

    The device reports a length for the uploaded file, but the number it
    returns is wrong for the files that are rendered here: a 14 second file
    came back as 2 seconds. The real length is measured locally instead, so
    the file is not removed while it is still playing.
    """
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return 0

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as err:
        _LOGGER.warning("Could not measure the length of %s: %s", path, err)
        return 0

    if result.returncode != 0:
        return 0

    try:
        return int(float(result.stdout.strip()))
    except ValueError:
        return 0


def _remove_file(path: str) -> None:
    """Remove a file and ignore a missing one."""
    import os

    try:
        os.remove(path)
    except OSError:
        pass


def _cleanup_folder(folder: str) -> None:
    """Keep only the most recent renderings on disk.

    Every rendering creates a new file, without this the folder would grow
    forever. Only the newest files are kept so the same text can still be
    repeated without rendering it again.
    """
    import os

    try:
        entries = [os.path.join(folder, name) for name in os.listdir(folder)]
    except OSError:
        return

    files = [path for path in entries if os.path.isfile(path)]
    if len(files) <= TTS_MAX_CACHE_FILES:
        return

    files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    for path in files[TTS_MAX_CACHE_FILES:]:
        _remove_file(path)
