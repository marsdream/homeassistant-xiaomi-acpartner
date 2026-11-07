"""Infrared remote entity for the Xiaomi Air Conditioning Companion.

The device can learn infrared commands (into storage slots) and replay them,
and it can also send raw air conditioning command strings. Both are exposed
through a standard Home Assistant ``remote`` entity.

Command syntax
--------------

``remote.send_command`` accepts one of:

* ``model:code[:slot]`` — a learned command; ``model`` and ``code`` are
  hexadecimal strings, ``slot`` is the storage slot (0-134).
* anything else — sent verbatim as an air conditioning command string
  (``send_cmd``).

``remote.learn_command`` accepts a slot number as its command string, e.g.
``"30"``. The learning session is stopped with ``remote.delete_command``.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_device_info
from .const import DEFAULT_IR_SLOT, DOMAIN
from .coordinator import XiaomiAcCompanionCoordinator

_LOGGER = logging.getLogger(__name__)


def _slot_from(command: Any) -> int:
    """Extract a storage slot number from a command string."""
    if isinstance(command, (list, tuple)):
        command = " ".join(str(part) for part in command)
    for part in str(command or "").split():
        if part.isdigit():
            return int(part)
    return DEFAULT_IR_SLOT


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the infrared remote entity."""
    coordinator: XiaomiAcCompanionCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([XiaomiAcCompanionRemote(coordinator, entry)])


class XiaomiAcCompanionRemote(CoordinatorEntity[XiaomiAcCompanionCoordinator], RemoteEntity):
    """Expose the infrared capabilities of the device."""

    _attr_should_poll = False

    def __init__(
        self, coordinator: XiaomiAcCompanionCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialise the remote."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"{coordinator.name} 红外"
        self._attr_unique_id = f"{entry.entry_id}-remote"
        self._attr_device_info = get_device_info(entry, coordinator.name)
        self._attr_supported_features = (
            RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
        )

    @property
    def available(self) -> bool:
        """Return whether the device is reachable."""
        return self.coordinator.last_update_success

    async def async_learn_command(
        self, command: Any = None, code: str | None = None, **kwargs: Any
    ) -> None:
        """Start learning an infrared command into a storage slot."""
        slot = _slot_from(command)
        _LOGGER.debug("Starting IR learn on slot %s", slot)
        await self.coordinator.device.async_ir_learn_start(slot)

    async def async_delete_command(self, command: Any = None, **kwargs: Any) -> None:
        """Stop an ongoing learning session."""
        slot = _slot_from(command)
        await self.coordinator.device.async_ir_learn_stop(slot)

    async def async_send_command(self, command: Any, **kwargs: Any) -> None:
        """Send an infrared command."""
        if isinstance(command, (list, tuple)):
            command = " ".join(str(part) for part in command)
        command = str(command)

        if ":" in command:
            parts = command.split(":")
            model = parts[0]
            code = parts[1]
            slot = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            await self.coordinator.device.async_send_learned_ir_code(model, code, slot)
            return

        await self.coordinator.device.async_send_ir_code(command)

    async def async_get_ir_learn_result(self) -> Any:
        """Return the last learned infrared command."""
        return await self.coordinator.device.async_ir_learn_result()
