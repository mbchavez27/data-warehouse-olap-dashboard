"""Tests for etl/transform.py. No database, no network."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import transform

BANDS = [(0, 0, 0), (1, 1, 6), (2, 7, 10), (3, 11, 15), (4, 16, 2147483647)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("M", "M"), ("Male", "M"), ("male", "M"), ("F", "F"), ("Female", "F"), (" FEMALE ", "F")],
)
def test_gender_normalizes_every_source_spelling(raw, expected):
    assert transform.normalize_gender(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "X", "Unknown", "Mal"])
def test_gender_rejects_values_it_cannot_map(raw):
    with pytest.raises(ValueError, match="unmapped gender"):
        transform.normalize_gender(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bike", "Bicycle"),
        ("Bicycle", "Bicycle"),
        ("Motorbike", "Motorcycle"),
        ("Motorcycle", "Motorcycle"),
        ("Car", "Car"),
        ("Trike", "Trike"),
    ],
)
def test_vehicle_merges_only_spelling_variants(raw, expected):
    assert transform.normalize_vehicle(raw) == expected


def test_vehicle_rejects_unknown_labels():
    with pytest.raises(ValueError, match="unmapped vehicleType"):
        transform.normalize_vehicle("Scooter")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TOYS", "Toys"),
        ("Toy", "Toys"),
        ("Toys", "Toys"),
        ("BAG", "Bags"),
        ("Bags", "Bags"),
        ("make up", "Makeup"),
        ("Makeup", "Makeup"),
        ("GADGETS", "Gadgets"),
        ("Gadgets", "Gadgets"),
        ("Clothes", "Clothes"),
        ("Men's Apparel", "Men's Apparel"),
        ("Electronics", "Electronics"),
        ("Appliances", "Appliances"),
        ("Laptops", "Laptops"),
    ],
)
def test_category_maps_all_14_source_labels_to_9_categories(raw, expected):
    assert transform.normalize_category(raw) == expected


def test_category_map_has_exactly_nine_targets():
    assert len(set(transform.CATEGORIES.values())) == 9


def test_category_keeps_distinct_concepts_apart():
    assert transform.normalize_category("Clothes") != transform.normalize_category("Men's Apparel")
    assert transform.normalize_category("Gadgets") != transform.normalize_category("Electronics")


def test_category_rejects_unknown_labels():
    with pytest.raises(ValueError, match="unmapped category"):
        transform.normalize_category("Furniture")


@pytest.mark.parametrize(
    ("age", "band"),
    [(18, "18-29"), (29, "18-29"), (30, "30-39"), (39, "30-39"), (40, "40-49"),
     (49, "40-49"), (50, "50-60"), (60, "50-60"), (None, None)],
)
def test_age_band_uses_inclusive_decade_bounds(age, band):
    assert transform.rider_age_band(age) == band


@pytest.mark.parametrize("age", [17, 61, -1])
def test_age_band_rejects_ages_outside_the_bands(age):
    with pytest.raises(ValueError, match="outside the defined bands"):
        transform.rider_age_band(age)


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [("Ana", "Cruz", "Ana Cruz"), (" Ana ", " Cruz ", "Ana Cruz"), ("Ana", None, "Ana"),
     (None, "Cruz", "Cruz"), ("Ana", "", "Ana")],
)
def test_full_name_joins_present_parts(first, last, expected):
    assert transform.full_name(first, last) == expected


@pytest.mark.parametrize(("first", "last"), [(None, None), ("", " ")])
def test_full_name_rejects_empty_names(first, last):
    with pytest.raises(ValueError, match="no first or last part"):
        transform.full_name(first, last)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19.99", Decimal("19.99")),
        ("1.77046", Decimal("1.77")),
        ("3.27517", Decimal("3.28")),
        ("2.675", Decimal("2.68")),  # a tie rounds up when read as text
        ("9999.42", Decimal("9999.42")),
        ("100", Decimal("100.00")),
    ],
)
def test_list_price_rounds_half_up_to_centavos(raw, expected):
    assert transform.to_list_price(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", "-1", "NaN", "Infinity"])
def test_list_price_rejects_non_prices(raw):
    with pytest.raises(ValueError, match="price"):
        transform.to_list_price(raw)


@pytest.mark.parametrize(
    ("units", "key"),
    [(1, 1), (6, 1), (7, 2), (10, 2), (11, 3), (15, 3), (16, 4), (34, 4)],
)
def test_size_band_follows_the_warehouse_seed_boundaries(units, key):
    assert transform.size_band_key(units, BANDS) == key


@pytest.mark.parametrize("units", [0, -3])
def test_size_band_rejects_quantities_no_band_covers(units):
    with pytest.raises(ValueError, match="size bands"):
        transform.size_band_key(units, BANDS)
