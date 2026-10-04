"""Import Moj Elektro data into Home Assistant long-term statistics."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import MojElektroApi
from .const import DOMAIN, REFRESH_DAYS
from .tariffs import TZ, UserPrices, first_incomplete_day, hourly_costs, month_start, to_hours

_LOGGER = logging.getLogger(__name__)


def statistic_ids(usage_point: str) -> tuple[str, str]:
    slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", usage_point.lower())).strip("_") or "meter"
    return f"{DOMAIN}:{slug}_energy", f"{DOMAIN}:{slug}_cost"


class StatisticsImporter:
    def __init__(
        self,
        hass: HomeAssistant,
        api: MojElektroApi,
        usage_point: str,
        prices: UserPrices | None,
        history_days: int,
    ) -> None:
        self.hass = hass
        self.api = api
        self.usage_point = usage_point
        self.prices = prices
        self.history_days = history_days
        self.energy_id, self.cost_id = statistic_ids(usage_point)
        self._lock = asyncio.Lock()
        self.last_result: dict | None = None

    async def _has_statistics(self, statistic_id: str) -> bool:
        res = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, False, {"sum"}
        )
        return bool(res.get(statistic_id))

    async def _baseline(self, statistic_id: str, first: datetime) -> float:
        """Cumulative sum of the last hour strictly before `first`."""
        res = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            first - timedelta(days=400),
            first,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        cutoff = first.timestamp()
        rows = [r for r in res.get(statistic_id, []) if r.get("sum") is not None and r["start"] < cutoff]
        return float(max(rows, key=lambda r: r["start"])["sum"]) if rows else 0.0

    async def _import(self, statistic_id: str, name: str, unit: str, unit_class: str | None,
                      hours: dict[datetime, float]) -> tuple[float, float]:
        first = next(iter(hours))
        base = await self._baseline(statistic_id, first)
        cum = base
        stats = []
        for h, v in hours.items():
            cum += v
            stats.append({"start": h, "state": round(cum, 4), "sum": round(cum, 4)})
        metadata = {
            "has_sum": True,
            "mean_type": StatisticMeanType.NONE,
            "name": name,
            "source": DOMAIN,
            "statistic_id": statistic_id,
            "unit_class": unit_class,
            "unit_of_measurement": unit,
        }
        async_add_external_statistics(self.hass, metadata, stats)
        return base, cum - base

    async def async_run(self, start: date | None = None) -> dict:
        """Import whole days from `start` (default: last week, or the configured
        history on the first run) up to the last complete day."""
        async with self._lock:
            today = dt_util.now(TZ).date()
            if start is None:
                if await self._has_statistics(self.energy_id):
                    start = today - timedelta(days=REFRESH_DAYS)
                else:
                    start = today - timedelta(days=self.history_days)
            # Costs are per calendar month (billed power = the month's peaks),
            # so always recompute whole months.
            start = month_start(start)
            intervals = await self.api.async_fetch_intervals(start, today)
            cut = first_incomplete_day(intervals)
            if cut is not None:
                _LOGGER.info("Moj Elektro data for %s is incomplete; importing up to the day before", cut)
                intervals = {b: v for b, v in intervals.items() if b.astimezone(TZ).date() < cut}
            if not intervals:
                self.last_result = {"time": dt_util.utcnow().isoformat(), "hours": 0}
                _LOGGER.info("Moj Elektro: nothing to import from %s", start)
                return self.last_result
            energy_hours = to_hours(intervals)
            _, kwh = await self._import(
                self.energy_id, f"Moj Elektro {self.usage_point} energy", "kWh", "energy", energy_hours
            )
            eur = None
            if self.prices is not None:
                cost_hours = hourly_costs(intervals, self.prices)
                _, eur = await self._import(
                    self.cost_id, f"Moj Elektro {self.usage_point} cost",
                    self.hass.config.currency, None, cost_hours,
                )
            first = next(iter(energy_hours))
            last = next(reversed(energy_hours))
            self.last_result = {
                "time": dt_util.utcnow().isoformat(),
                "hours": len(energy_hours),
                "from": first.astimezone(TZ).isoformat(),
                "to": (last + timedelta(hours=1)).astimezone(TZ).isoformat(),
                "kwh": round(kwh, 3),
                "cost": None if eur is None else round(eur, 2),
            }
            _LOGGER.info("Moj Elektro import: %s", self.last_result)
            return self.last_result
