"""Moj Elektro Statistics: hourly consumption and cost from Moj Elektro as
Home Assistant long-term statistics with the correct timestamps."""
from __future__ import annotations

import logging
from datetime import date

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import MojElektroApi, MojElektroError
from .const import (
    ATTR_FROM_DATE,
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
    IMPORT_HOURS,
    IMPORT_MINUTE,
    SERVICE_IMPORT_HISTORY,
)
from .importer import StatisticsImporter
from .tariffs import UserPrices

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_FROM_DATE): cv.date})


def _prices(conf: dict) -> UserPrices | None:
    energy = conf.get(CONF_ENERGY_PRICE)
    if not energy:
        return None
    return UserPrices(
        energy=float(energy),
        monthly_fee=float(conf.get(CONF_MONTHLY_FEE, DEFAULT_MONTHLY_FEE) or 0),
        vat=float(conf.get(CONF_VAT, DEFAULT_VAT)),
    )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def handle_import(call: ServiceCall) -> None:
        start: date | None = call.data.get(ATTR_FROM_DATE)
        for importer in hass.data.get(DOMAIN, {}).values():
            await importer.async_run(start)

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, handle_import, schema=SERVICE_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    conf = {**entry.data, **entry.options}
    api = MojElektroApi(async_get_clientsession(hass), conf[CONF_TOKEN], conf[CONF_USAGE_POINT])
    importer = StatisticsImporter(
        hass, api, conf[CONF_USAGE_POINT], _prices(conf),
        int(conf.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = importer

    async def run(_now=None) -> None:
        try:
            await importer.async_run()
        except MojElektroError as err:
            _LOGGER.warning("Moj Elektro import failed: %s", err)
        except Exception:  # noqa: BLE001 - keep the schedule alive
            _LOGGER.exception("Moj Elektro import failed")

    @callback
    def start_background(_event=None) -> None:
        entry.async_create_background_task(hass, run(), f"{DOMAIN}_initial_import")

    entry.async_on_unload(
        async_track_time_change(hass, run, hour=list(IMPORT_HOURS), minute=IMPORT_MINUTE, second=0)
    )
    if hass.state is CoreState.running:
        start_background()
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, start_background))
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
