"""Unit tests for the tariff model (no Home Assistant needed)."""
import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "tariffs", Path(__file__).parents[1] / "custom_components/mojelektro_stats/tariffs.py"
)
t = importlib.util.module_from_spec(_spec)
sys.modules["tariffs"] = t
_spec.loader.exec_module(t)


def local(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=t.TZ)


def test_easter():
    assert t.easter(2026) == date(2026, 4, 5)
    assert t.easter(2027) == date(2027, 3, 28)


def test_time_blocks_summer():
    wed = (2026, 8, 5)
    assert t.time_block(local(*wed, 8)) == 2
    assert t.time_block(local(*wed, 14)) == 3
    assert t.time_block(local(*wed, 6)) == 3
    assert t.time_block(local(*wed, 23)) == 4
    sat = (2026, 8, 8)
    assert t.time_block(local(*sat, 8)) == 3
    assert t.time_block(local(*sat, 23)) == 5
    assert t.time_block(local(2026, 4, 6, 8)) == 3  # Easter Monday is a day off


def test_time_blocks_winter():
    assert t.time_block(local(2026, 1, 7, 8)) == 1
    assert t.time_block(local(2026, 1, 7, 15)) == 2
    assert t.time_block(local(2026, 1, 7, 2)) == 3
    assert t.time_block(local(2026, 1, 10, 2)) == 4  # Saturday night


def test_billed_power_matches_bills():
    # January 2026: peaks per block from the 15-minute data -> 2.9 / 4.5 / 4.5 / 4.5 on the bill
    assert t.billed_power({1: 2.92, 2: 4.46, 3: 2.34, 4: 1.58}, [1, 2, 3, 4]) == {1: 2.9, 2: 4.5, 3: 4.5, 4: 4.5}
    # June 2026: 3.1 / 3.7 / 3.7 / 3.7
    assert t.billed_power({2: 3.12, 3: 3.66, 4: 2.9, 5: 1.4}, [2, 3, 4, 5]) == {2: 3.1, 3: 3.7, 4: 3.7, 5: 3.7}


def _flat_month(m, kwh=0.1):
    vals = {}
    cur, end = t.utc_midnight(m), t.utc_midnight(t.next_month(m))
    while cur < end:
        vals[cur] = kwh
        cur += timedelta(minutes=15)
    return vals


def test_month_costs_january_fixed_part():
    vals = _flat_month(date(2026, 1, 1))
    vals[local(2026, 1, 7, 8).astimezone(timezone.utc)] = 2.92 / 4   # block 1 peak
    vals[local(2026, 1, 7, 14).astimezone(timezone.utc)] = 4.46 / 4  # block 2 peak
    _, months = t.month_costs(vals, t.UserPrices(energy=0.1089, monthly_fee=0.99))
    res = months[date(2026, 1, 1)]
    assert res.power_by_block == {1: 2.9, 2: 4.5, 3: 4.5, 4: 4.5}
    assert round(res.parts["network_power"], 2) == 9.82   # bill: 4.96 + 4.11 + 0.73 + 0.02
    assert round(res.parts["spte_ove"], 2) == 1.12        # bill: 2.9 kW x 0.38781


def test_hourly_costs_add_up_to_month_total():
    m = date(2026, 3, 1)
    prices = t.UserPrices(energy=0.1089, monthly_fee=0.99)
    vals = _flat_month(m)
    hours = t.hourly_costs(vals, prices)
    _, months = t.month_costs(vals, prices)
    assert abs(sum(hours.values()) - months[m].total * 1.22) < 1e-6
    assert len(hours) == 743  # DST change in March


def test_hours_in_month_dst():
    assert t.hours_in_month(date(2026, 3, 1)) == 743
    assert t.hours_in_month(date(2026, 10, 1)) == 745


def test_first_incomplete_day():
    vals = _flat_month(date(2026, 3, 1))
    assert t.first_incomplete_day(vals) is None  # 29 March has 92 intervals, still complete
    for h in range(9, 24):
        vals[local(2026, 3, 20, h).astimezone(timezone.utc)] = 0.0
    assert t.first_incomplete_day(vals) == date(2026, 3, 20)
