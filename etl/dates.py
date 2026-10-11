"""Strict source-date parsing and deterministic DIM_DATE row derivation."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional


SOURCE_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")


def parse_delivery_date(raw: Optional[str]) -> date:
    """Parse one source Orders.deliveryDate or fail without inventing a date."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"deliveryDate is missing or invalid: {raw!r}")

    for date_format in SOURCE_DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, date_format).date()
        except ValueError:
            continue
        if parsed.strftime(date_format) == raw:
            return parsed

    raise ValueError(
        f"deliveryDate {raw!r} must be YYYY-MM-DD or MM/DD/YYYY and calendar-valid"
    )


def derive_date_row(full_date: date) -> Dict[str, object]:
    """Return the eleven DIM_DATE columns for one calendar date."""
    last_day = calendar.monthrange(full_date.year, full_date.month)[1]
    return {
        "dateKey": int(full_date.strftime("%Y%m%d")),
        "fullDate": full_date,
        "dayOfMonth": full_date.day,
        "dayName": full_date.strftime("%A"),
        "isWeekend": full_date.isoweekday() in (6, 7),
        "isPayDay": full_date.day in (15, last_day),
        "weekOfYear": full_date.isocalendar().week,
        "monthNumber": full_date.month,
        "monthName": full_date.strftime("%B"),
        "quarter": ((full_date.month - 1) // 3) + 1,
        "year": full_date.year,
    }


def build_date_rows(raw_dates: Iterable[Optional[str]]) -> List[Dict[str, object]]:
    """Parse source values, then expand their min/max to a closed calendar range."""
    parsed_dates = [parse_delivery_date(raw) for raw in raw_dates]
    if not parsed_dates:
        raise ValueError("source Orders contains no deliveryDate values")

    first_date = min(parsed_dates)
    last_date = max(parsed_dates)
    day_count = (last_date - first_date).days + 1
    return [derive_date_row(first_date + timedelta(days=offset)) for offset in range(day_count)]
