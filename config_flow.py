"""UI setup for the FranklinWH integration."""

from __future__ import annotations

import logging
from typing import Any

import franklinwh
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_ID, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback

from .device import DOMAIN
from .local import DEFAULT_LOCAL_PORT, LOCAL_TIMEOUT, read_power_flow

_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_INTERVAL = 30


def _options_schema(defaults: dict[str, Any]) -> dict:
    """Fields that can be changed later from the integration's Configure button."""
    return {
        vol.Optional(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_LOCAL_PORT)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(
            "tolerate_stale_data", default=defaults.get("tolerate_stale_data", True)
        ): bool,
        vol.Optional(
            "update_interval",
            default=defaults.get("update_interval", DEFAULT_UPDATE_INTERVAL),
        ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
    }


async def _check_local(hass: HomeAssistant, host: str, port: int) -> bool:
    """True if the aGate answers on the LAN."""
    try:
        await hass.async_add_executor_job(read_power_flow, host, port, LOCAL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("FranklinWH aGate not reachable at %s:%s: %s", host, port, e)
        return False
    return True


async def _check_cloud(username: str, password: str) -> str | None:
    """None if the cloud login works, else an error key."""
    try:
        await franklinwh.TokenFetcher(username, password).get_token()
    except franklinwh.client.InvalidCredentialsException:
        return "invalid_auth"
    except franklinwh.client.AccountLockedException:
        return "account_locked"
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("FranklinWH cloud login check failed: %s", e)
        return "cannot_connect"
    return None


class FranklinWHConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FranklinWH."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account, gateway serial and (optionally) the aGate's IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            gateway = user_input[CONF_ID].strip()
            await self.async_set_unique_id(gateway)
            self._abort_if_unique_id_configured()

            host = (user_input.get(CONF_HOST) or "").strip()
            port = user_input.get(CONF_PORT, DEFAULT_LOCAL_PORT)
            local_ok = bool(host) and await _check_local(self.hass, host, port)
            cloud_error = await _check_cloud(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )

            if host and not local_ok:
                errors[CONF_HOST] = "cannot_connect_local"
            elif cloud_error in ("invalid_auth", "account_locked"):
                errors["base"] = cloud_error
            elif cloud_error and not local_ok:
                # Cloud is down and there's no working local path: nothing to read.
                errors["base"] = cloud_error

            if not errors:
                data = {**user_input, CONF_ID: gateway, CONF_HOST: host}
                return self.async_create_entry(title=f"FranklinWH {gateway}", data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_ID): str,
                **_options_schema(user_input or {}),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Allow changing the aGate IP and polling settings later."""
        return FranklinWHOptionsFlow()


class FranklinWHOptionsFlow(OptionsFlow):
    """Change the aGate IP, port, stale-data and polling settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            port = user_input.get(CONF_PORT, DEFAULT_LOCAL_PORT)
            if host and not await _check_local(self.hass, host, port):
                errors[CONF_HOST] = "cannot_connect_local"
            else:
                return self.async_create_entry(data={**user_input, CONF_HOST: host})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_options_schema(user_input or current)),
            errors=errors,
        )
