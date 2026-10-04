"""Minimal client for the Moj Elektro API (api.informatika.si)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import aiohttp

from .tariffs import TZ

_LOGGER = logging.getLogger(__name__)

BASE = "https://api.informatika.si/mojelektro/v1"
# 15-minute active energy taken from the grid (kWh per interval).
READING_15MIN = "32.0.2.4.1.2.12.0.0.0.0.0.0.0.0.3.72.0"
CHUNK_DAYS = 30
PAUSE_SECONDS = 3
MAX_RETRIES = 6


class MojElektroError(Exception):
    """Generic API error."""


class MojElektroAuthError(MojElektroError):
    """Token or usage point rejected."""


class MojElektroApi:
    def __init__(self, session: aiohttp.ClientSession, token: str, usage_point: str) -> None:
        self._session = session
        self._token = token
        self._usage_point = usage_point

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-TOKEN": self._token, "accept": "application/json"}

    async def async_validate(self) -> None:
        """Check token and usage point (EIMM) with the metering point endpoint."""
        await self._get_json(f"{BASE}/merilno-mesto/{self._usage_point}")

    async def _get_json(self, url: str) -> dict:
        for attempt in range(MAX_RETRIES):
            async with self._session.get(url, headers=self._headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 429:
                    wait = 30 * (attempt + 1)
                    _LOGGER.info("Moj Elektro rate limit, waiting %s s", wait)
                    await asyncio.sleep(wait)
                    continue
                if r.status in (401, 403, 404):
                    raise MojElektroAuthError(f"HTTP {r.status}")
                if r.status != 200:
                    raise MojElektroError(f"HTTP {r.status} for {url.split('?')[0]}")
                return await r.json()
        raise MojElektroError("Still rate-limited after retries")

    async def async_fetch_intervals(self, start: date, end: date) -> dict[datetime, float]:
        """{interval start (UTC): kWh} for local dates start <= d < end, deduplicated."""
        vals: dict[datetime, float] = {}
        d = start
        while d < end:
            e = min(d + timedelta(days=CHUNK_DAYS), end)
            url = (
                f"{BASE}/meter-readings?usagePoint={self._usage_point}"
                f"&startTime={d.isoformat()}&endTime={e.isoformat()}"
                f"&option=ReadingType%3D{READING_15MIN}"
            )
            data = await self._get_json(url)
            for blk in data.get("intervalBlocks") or []:
                if blk.get("readingType") != READING_15MIN:
                    continue
                for rd in blk.get("intervalReadings") or []:
                    # The timestamp marks the END of the 15-minute interval.
                    begin = datetime.fromisoformat(rd["timestamp"]) - timedelta(minutes=15)
                    if start <= begin.astimezone(TZ).date() < end:
                        vals[begin.astimezone(timezone.utc)] = float(rd["value"])
            d = e
            if d < end:
                await asyncio.sleep(PAUSE_SECONDS)
        return vals
