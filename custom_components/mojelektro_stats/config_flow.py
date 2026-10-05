"""Config flow for Moj Elektro Statistics."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import MojElektroApi, MojElektroAuthError, MojElektroError, create_session
from .const import (
    CONF_ENERGY_PRICE,
    CONF_HISTORY_DAYS,
    CONF_MONTHLY_FEE,
    CONF_TOKEN,
    CONF_USAGE_POINT,
    CONF_VAT,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_MONTHLY_FEE,
    DEFAULT_VAT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PRICE = selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=10, step="any", mode=selector.NumberSelectorMode.BOX)
)


def _price_fields(d: dict[str, Any]) -> dict:
    return {
        vol.Optional(CONF_ENERGY_PRICE, description={"suggested_value": d.get(CONF_ENERGY_PRICE)}): PRICE,
        vol.Optional(CONF_MONTHLY_FEE, default=d.get(CONF_MONTHLY_FEE, DEFAULT_MONTHLY_FEE)): PRICE,
        vol.Optional(CONF_VAT, default=d.get(CONF_VAT, DEFAULT_VAT)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=1, step=0.01, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_HISTORY_DAYS, default=d.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=1095, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
    }


class MojElektroStatsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            usage_point = user_input[CONF_USAGE_POINT].strip()
            await self.async_set_unique_id(usage_point)
            self._abort_if_unique_id_configured()
            session = create_session()
            api = MojElektroApi(session, user_input[CONF_TOKEN].strip(), usage_point)
            try:
                await api.async_validate()
            except MojElektroAuthError as err:
                _LOGGER.warning("Moj Elektro rejected token or usage point: %s", err)
                errors["base"] = "invalid_auth"
            except MojElektroError as err:
                _LOGGER.warning("Moj Elektro API error during setup: %s", err)
                # A wrong token (or EIMM) makes the API answer HTTP 500.
                errors["base"] = "check_credentials" if err.status == 500 else "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while checking Moj Elektro")
                errors["base"] = "cannot_connect"
            else:
                data = {CONF_TOKEN: user_input[CONF_TOKEN].strip(), CONF_USAGE_POINT: usage_point}
                options = {k: v for k, v in user_input.items() if k not in data}
                return self.async_create_entry(title=f"Moj Elektro {usage_point}", data=data, options=options)
            finally:
                await session.close()
        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_USAGE_POINT): str,
                **_price_fields(user_input or {}),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MojElektroStatsOptionsFlow()


class MojElektroStatsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_price_fields(dict(self.config_entry.options)))
        )
