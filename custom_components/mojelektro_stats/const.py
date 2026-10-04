"""Constants for Moj Elektro Statistics."""
from __future__ import annotations

DOMAIN = "mojelektro_stats"

CONF_TOKEN = "token"
CONF_USAGE_POINT = "usage_point"
CONF_ENERGY_PRICE = "energy_price"
CONF_MONTHLY_FEE = "monthly_fee"
CONF_VAT = "vat"
CONF_HISTORY_DAYS = "history_days"

DEFAULT_VAT = 0.22
DEFAULT_MONTHLY_FEE = 0.0
DEFAULT_HISTORY_DAYS = 365

# Moj Elektro data is published with about a day of delay, sometimes during the
# day, so the import runs twice a day and always re-imports the last week.
IMPORT_HOURS = (9, 15)
IMPORT_MINUTE = 5
REFRESH_DAYS = 7

SERVICE_IMPORT_HISTORY = "import_history"
ATTR_FROM_DATE = "from_date"
