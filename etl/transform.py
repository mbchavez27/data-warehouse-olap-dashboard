"""Row-level wrangling rules for the dimension and fact loads.

Pure functions, no database access. Every rule either returns the cleaned
value or raises ValueError naming the bad input; the loaders turn those errors
into reject records and abort, so nothing is silently guessed.
Rules and their rationale: docs/database/data-warehouse-implementation.md.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Sequence, Tuple

GENDERS = {"m": "M", "male": "M", "f": "F", "female": "F"}

# Only spelling variants of the same vehicle merge.
VEHICLES = {
    "bicycle": "Bicycle",
    "bike": "Bicycle",
    "motorcycle": "Motorcycle",
    "motorbike": "Motorcycle",
    "car": "Car",
    "trike": "Trike",
}

# Only case, spacing, and singular/plural variants merge; distinct concepts
# (Clothes vs Men's Apparel, Gadgets vs Electronics) stay separate.
CATEGORIES = {
    "toys": "Toys",
    "toy": "Toys",
    "bags": "Bags",
    "bag": "Bags",
    "makeup": "Makeup",
    "make up": "Makeup",
    "gadgets": "Gadgets",
    "clothes": "Clothes",
    "men's apparel": "Men's Apparel",
    "electronics": "Electronics",
    "appliances": "Appliances",
    "laptops": "Laptops",
}

# Decade bands (inclusive bounds).
AGE_BANDS: Tuple[Tuple[int, int, str], ...] = (
    (18, 29, "18-29"),
    (30, 39, "30-39"),
    (40, 49, "40-49"),
    (50, 60, "50-60"),
)

CENTAVO = Decimal("0.01")


def _key(raw: Optional[str]) -> str:
    return " ".join(raw.split()).lower() if isinstance(raw, str) else ""


def _lookup(table: dict, raw: Optional[str], what: str) -> str:
    value = table.get(_key(raw))
    if value is None:
        raise ValueError(f"unmapped {what}: {raw!r}")
    return value


def normalize_gender(raw: Optional[str]) -> str:
    """M / F / Male / Female (any case) -> 'M' or 'F'."""
    return _lookup(GENDERS, raw, "gender")


def normalize_vehicle(raw: Optional[str]) -> str:
    """Source vehicle label -> one of Bicycle, Motorcycle, Car, Trike."""
    return _lookup(VEHICLES, raw, "vehicleType")


def normalize_category(raw: Optional[str]) -> str:
    """Source category label -> one of the 9 canonical categories."""
    return _lookup(CATEGORIES, raw, "category")


def rider_age_band(age: Optional[int]) -> Optional[str]:
    """Age -> decade band; None stays None (DIM_RIDER.age is nullable)."""
    if age is None:
        return None
    for low, high, label in AGE_BANDS:
        if low <= age <= high:
            return label
    raise ValueError(f"rider age outside the defined bands (18-60): {age!r}")


def full_name(first: Optional[str], last: Optional[str]) -> str:
    """'First Last'; a missing part is skipped, both missing is an error."""
    parts = [p.strip() for p in (first, last) if isinstance(p, str) and p.strip()]
    if not parts:
        raise ValueError(f"name has no first or last part: {first!r} {last!r}")
    return " ".join(parts)


def to_list_price(raw: Optional[str]) -> Decimal:
    """Price text -> NUMERIC(12,2), rounding half away from zero.

    Takes the price as text (Postgres prints REAL with the digits stored in the
    dump, e.g. '1.77046'), not as a binary float, so ties such as '2.675'
    round exactly as written.
    """
    try:
        value = Decimal(raw)
    except (InvalidOperation, TypeError):
        raise ValueError(f"price is not a number: {raw!r}") from None
    if not value.is_finite() or value < 0:
        raise ValueError(f"price must be a finite, non-negative amount: {raw!r}")
    return value.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def size_band_key(total_quantity: int, bands: Sequence[Tuple[int, int, int]]) -> int:
    """Total order units -> orderSizeKey, using (key, min, max) rows from
    DIM_ORDERSIZE so the warehouse seed stays the single source of truth."""
    matches = [key for key, low, high in bands if key != 0 and low <= total_quantity <= high]
    if len(matches) != 1:
        raise ValueError(
            f"order quantity {total_quantity!r} matches {len(matches)} size bands; expected 1"
        )
    return matches[0]
