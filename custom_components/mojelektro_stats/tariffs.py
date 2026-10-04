"""Slovenian network tariff time blocks and monthly cost model.

Pure Python (no Home Assistant imports) so it can be unit-tested on its own.

Validated against five 2026 GEN-I bills of one household (user group 0, low
voltage, no agreed power set): January, March, April, June and August 2026 were
reproduced to within 0.12 EUR, including the billed power per block.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Ljubljana")

FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (2, 8), (4, 27), (5, 1), (5, 2), (6, 25), (8, 15),
    (10, 31), (11, 1), (12, 25), (12, 26),
}

# Network tariffs (omrežnina) and state levies, EUR excl. VAT, for user group 0.
# Each period applies from its "from" date until the next one. "net_kwh" is per kWh
# taken in a block, "power_kw" per kW of billed power per month, "spte_kw" is the
# SPTE/OVE contribution per kW of the first block's billed power per month.
# "extra_kwh" = market operator (0.00013) + energy efficiency (0.0008) + excise (0.00153).
TARIFF_PERIODS: list[dict] = [
    {
        "from": date(2025, 1, 1),
        "note": "Read from 2026 bills; months before 2026 are approximate.",
        "extra_kwh": 0.00246,
        "summer": {
            "net_kwh": {2: 0.01998, 3: 0.01717, 4: 0.01805, 5: 0.01299},
            "power_kw": {2: 1.09230, 3: 0.28902, 4: 0.02436, 5: 0.00245},
            "spte_kw": 0.77562,
        },
        "winter": {
            "net_kwh": {1: 0.01998, 2: 0.01833, 3: 0.01809, 4: 0.01855},
            "power_kw": {1: 1.71126, 2: 0.91224, 3: 0.16297, 4: 0.00407},
            # Halved by government decree for 1.11.2025-28.2.2026.
            "spte_kw": 0.38781,
        },
    },
]


def easter(year: int) -> date:
    """Easter Sunday (Gregorian)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(year, (h + l - 7 * m + 114) // 31, ((h + l - 7 * m + 114) % 31) + 1)


def is_day_off(d: date) -> bool:
    """Weekend or Slovenian public holiday (Easter Sunday is always a Sunday)."""
    return d.weekday() >= 5 or (d.month, d.day) in FIXED_HOLIDAYS or d == easter(d.year) + timedelta(days=1)


def season(d: date) -> str:
    """Higher season (winter) is November-February."""
    return "winter" if d.month in (11, 12, 1, 2) else "summer"


def time_block(t: datetime) -> int:
    """Time block 1-5 for a local datetime (the start of a 15-minute interval)."""
    t = t.astimezone(TZ)
    h = t.hour
    if h <= 5 or h >= 22:
        level = 2
    elif h in (6, 14, 15, 20, 21):
        level = 1
    else:
        level = 0
    base = 1 if season(t.date()) == "winter" else 2
    return base + level + (1 if is_day_off(t.date()) else 0)


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def utc_midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), TZ).astimezone(timezone.utc)


def hours_in_month(m: date) -> float:
    return (utc_midnight(next_month(m)) - utc_midnight(m)).total_seconds() / 3600


def tariff_for(m: date) -> dict:
    chosen = TARIFF_PERIODS[0]
    for per in sorted(TARIFF_PERIODS, key=lambda p: p["from"]):
        if per["from"] <= m:
            chosen = per
    return chosen


@dataclass
class UserPrices:
    """Supplier prices, EUR excl. VAT."""

    energy: float           # per kWh (single tariff, ET)
    monthly_fee: float      # per month, after supplier discounts
    vat: float = 0.22


@dataclass
class MonthResult:
    kwh_by_block: dict[int, float]
    power_by_block: dict[int, float]
    parts: dict[str, float]

    @property
    def fixed(self) -> float:
        return self.parts["network_power"] + self.parts["spte_ove"] + self.parts["monthly_fee"]

    @property
    def total(self) -> float:
        return sum(self.parts.values())


def billed_power(peaks_kw: dict[int, float], blocks: list[int]) -> dict[int, float]:
    """Billed power per block: the month's highest 15-minute peak in that block,
    rounded to 0.1 kW, and never lower than the block before it."""
    power: dict[int, float] = {}
    prev = 0.0
    for b in sorted(blocks):
        pk = int(peaks_kw.get(b, 0.0) * 10 + 0.5) / 10
        prev = max(prev, pk)
        power[b] = prev
    return power


def month_costs(
    intervals: dict[datetime, float], prices: UserPrices
) -> tuple[dict[datetime, float], dict[date, MonthResult]]:
    """Variable cost per interval (EUR excl. VAT) and a per-month breakdown.

    intervals: {interval start (aware datetime): kWh}
    """
    by_month: dict[date, list[tuple[datetime, int, float]]] = {}
    for begin, kwh in intervals.items():
        local = begin.astimezone(TZ)
        by_month.setdefault(month_start(local.date()), []).append((begin, time_block(local), kwh))
    variable: dict[datetime, float] = {}
    months: dict[date, MonthResult] = {}
    for m, items in sorted(by_month.items()):
        per = tariff_for(m)
        s = per[season(m)]
        peaks: dict[int, float] = {}
        kwh_b: dict[int, float] = {}
        for begin, b, kwh in items:
            peaks[b] = max(peaks.get(b, 0.0), kwh * 4)
            kwh_b[b] = kwh_b.get(b, 0.0) + kwh
            variable[begin] = kwh * (prices.energy + per["extra_kwh"] + s["net_kwh"][b])
        power = billed_power(peaks, list(s["power_kw"]))
        first = min(s["power_kw"])
        total_kwh = sum(kwh_b.values())
        parts = {
            "energy": total_kwh * prices.energy,
            "network_energy": sum(kwh_b[b] * s["net_kwh"][b] for b in kwh_b),
            "network_power": sum(power[b] * s["power_kw"][b] for b in power),
            "spte_ove": power[first] * s["spte_kw"],
            "levies_excise": total_kwh * per["extra_kwh"],
            "monthly_fee": prices.monthly_fee,
        }
        months[m] = MonthResult(kwh_b, power, parts)
    return variable, months


def to_hours(series: dict[datetime, float]) -> dict[datetime, float]:
    """Sum values per UTC hour; keys are aware UTC datetimes at the top of the hour."""
    hours: dict[datetime, float] = {}
    for begin, v in series.items():
        h = begin.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        hours[h] = hours.get(h, 0.0) + v
    return dict(sorted(hours.items()))


def hourly_costs(intervals: dict[datetime, float], prices: UserPrices) -> dict[datetime, float]:
    """Cost per hour incl. VAT: variable cost plus the month's fixed part spread
    evenly over all hours of that month."""
    variable, months = month_costs(intervals, prices)
    hours = to_hours(variable)
    for h in hours:
        m = month_start(h.astimezone(TZ).date())
        hours[h] += months[m].fixed / hours_in_month(m)
    return {h: v * (1 + prices.vat) for h, v in hours.items()}


def first_incomplete_day(intervals: dict[datetime, float], max_zeros: int = 8) -> date | None:
    """First local day whose data is missing intervals or has suspiciously many
    zero readings (Moj Elektro fills not-yet-published intervals with 0)."""
    count: dict[date, int] = {}
    zeros: dict[date, int] = {}
    for begin, kwh in intervals.items():
        d = begin.astimezone(TZ).date()
        count[d] = count.get(d, 0) + 1
        zeros[d] = zeros.get(d, 0) + (1 if kwh == 0 else 0)
    for d in sorted(count):
        expected = int((utc_midnight(d + timedelta(days=1)) - utc_midnight(d)).total_seconds() // 900)
        if count[d] != expected or zeros[d] > max_zeros:
            return d
    return None
