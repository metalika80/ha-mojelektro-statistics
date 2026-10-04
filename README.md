# Moj Elektro Statistics

Home Assistant integration that imports your **hourly electricity consumption** from
[Moj Elektro](https://mojelektro.si) (the Slovenian national metering data hub) into
Home Assistant **long-term statistics with the correct timestamps**, and optionally the
**hourly cost**, including the network tariff time blocks (*časovni bloki*).

Moj Elektro publishes 15-minute data with about a day of delay. Sensor-based
integrations then record yesterday's consumption at the time it is fetched, so the
Energy dashboard shows it on the wrong day and hour. This integration writes each hour
where it belongs, the same way the official Opower or Tibber integrations backfill data.

> Not affiliated with Informatika, Elektro distribution companies or any supplier.

## What you get

Two external statistics per metering point, ready for the **Energy dashboard**:

| Statistic | Unit | Use in Energy dashboard |
|---|---|---|
| `mojelektro_stats:<eimm>_energy` | kWh | Electricity grid → *Energy imported from grid* |
| `mojelektro_stats:<eimm>_cost` | EUR | same grid connection → *Use an entity tracking the total costs* |

* Up to a year (configurable) of history on the first run.
* Runs at 09:05 and 15:05 and re-imports the last week, so late or corrected data is picked up.
* Only **complete days** are imported: Moj Elektro sometimes returns a day with most
  intervals still `0`; the import stops before such a day and fills it in later.
* Handles the API rate limit (HTTP 429) by waiting.
* Service `mojelektro_stats.import_history` (optional `from_date`) to re-import.

## Cost model

Hourly cost (incl. VAT) = kWh × (your energy price + network fee of that hour's time
block + state levies and excise) + the month's fixed part spread evenly over the month:
billed power per block, the SPTE/OVE contribution and your supplier's monthly fee.

* **Time blocks:** higher season Nov–Feb (blocks 1–4), lower season Mar–Oct (blocks 2–5);
  working day expensive 7–14 h and 16–20 h, medium 6 h, 14–16 h and 20–22 h, cheap 22–6 h;
  on weekends and public holidays every hour is one block cheaper.
* **Billed power:** the month's highest 15-minute peak in each block, rounded to 0.1 kW,
  never lower than the previous block. This applies when no agreed power is set
  (Moj Elektro shows `0.0`), which was the case for households during the 2025/26 transition.
* Validated against five 2026 bills (January, March, April, June, August) of one
  household: totals within 0.12 EUR, billed power per block exact.

**Limitations (please read):**

* Network tariffs are built in for **household user group 0** (low voltage). They are
  read from 2026 bills; months before 2026 are approximate. Tariffs change: the
  winter 2026/27 values are not in yet (pull requests welcome, see `tariffs.py`).
* Single-tariff (ET) energy price only for now.
* If you have an agreed power set in Moj Elektro, the power part of the cost will differ.

## Installation

HACS → ⋮ → *Custom repositories* → add `https://github.com/metalika80/ha-mojelektro-statistics`
(type *Integration*) → install → restart Home Assistant.

Manual: copy `custom_components/mojelektro_stats` into your `config/custom_components`.

## Configuration

Settings → Devices & services → Add integration → **Moj Elektro Statistics**:

* **API token:** mojelektro.si → *Moj profil* → *Kreiraj žeton* (choose no expiry).
* **Usage point (EIMM):** under *Merilna mesta*, e.g. `3-123456`.
* **Energy price** (EUR/kWh, without VAT) from your bill, e.g. *Električna energija ET*.
  Leave empty to import energy only.
* **Monthly fee** (EUR, without VAT) after discounts, e.g. *Mesečno nadomestilo* − *Eko popust*.
* **VAT** (default 0.22) and **days of history** for the first import (default 365).

Prices can be changed later under *Configure*; then run `mojelektro_stats.import_history`
with a `from_date` to recompute past months.

## Slovensko

Integracija uvozi urno porabo iz Moj Elektro v dolgoročno statistiko Home Assistanta
s pravimi časi (tudi za nazaj) in po želji urni strošek z omrežnino po časovnih blokih.
Nastavitev: žeton iz mojelektro.si (*Moj profil → Kreiraj žeton*), številka EIMM
merilnega mesta, cena energije in mesečno nadomestilo dobavitelja brez DDV. V nadzorni
plošči Energija izberi statistiko porabe kot porabo iz omrežja in statistiko stroška
kot entiteto skupnih stroškov.

## License

MIT
