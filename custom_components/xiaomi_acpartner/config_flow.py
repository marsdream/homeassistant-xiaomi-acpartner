"""Config flow for the Xiaomi Air Conditioning Companion integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.helpers.selector import AreaSelector

from .const import (
    CONF_NAME,
    CONF_TOKEN,
    CONF_TTS_API_KEY,
    CONF_TTS_API_URL,
    CONF_TTS_BASE_URL,
    DOMAIN,
)
from .device import XiaomiAcCompanion, XiaomiAcCompanionError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_TOKEN): str,
        vol.Optional(CONF_NAME, default=""): str,
        vol.Optional("area"): AreaSelector(),
    }
)


async def _probe(host: str, token: str) -> dict[str, Any]:
    """Verify the device answers and return its identity."""
    device = XiaomiAcCompanion(host, token)
    status = await device.async_status()
    radio = await device.async_radio_status()
    return {
        "model": status["model"],
        "state": status["state"],
        "load_power": status["load_power"],
        "radio_volume": radio.get("current_volume"),
    }


class XiaomiAcCompanionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Xiaomi Air Conditioning Companion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the device IP address and MiIO token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            token = user_input[CONF_TOKEN].strip()
            name = (user_input.get(CONF_NAME) or "").strip() or f"空调伴侣 {host}"

            if len(token) != 32:
                errors[CONF_TOKEN] = "invalid_token"
            else:
                try:
                    info = await _probe(host, token)
                except XiaomiAcCompanionError:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected error probing %s", host)
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(host)
                    self._abort_if_unique_id_configured()
                    self.context["title_placeholders"] = {"name": name}
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_HOST: host,
                            CONF_TOKEN: token,
                            CONF_NAME: name,
                            "area": user_input.get("area"),
                            "model": info["model"],
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow of this integration."""
        return XiaomiAcCompanionOptionsFlow()


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_TTS_API_KEY, default=""): str,
        vol.Optional(CONF_TTS_API_URL, default=""): str,
        vol.Optional(CONF_TTS_BASE_URL, default=""): str,
    }
)


class XiaomiAcCompanionOptionsFlow(OptionsFlow):
    """Let the user change the optional settings of an existing entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_TTS_API_KEY, "")
        api_url = self.config_entry.options.get(CONF_TTS_API_URL, "")
        base_url = self.config_entry.options.get(CONF_TTS_BASE_URL, "")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_TTS_API_KEY, default=current): str,
                    vol.Optional(CONF_TTS_API_URL, default=api_url): str,
                    vol.Optional(CONF_TTS_BASE_URL, default=base_url): str,
                }
            ),
        )
