"""Benchmark cases: which report levels run, with which parameters.

Each case is one query file plus one parameter set. Every report level runs
unfiltered (the heaviest, full-table case); the drill levels and slices that
users reach from the dashboard run too, so the baseline reflects real use.
Empty string means "all", exactly as the API will send it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class Case:
    case_id: str
    report: str
    query_file: str  # relative to olap/queries/
    params: Dict[str, str] = field(default_factory=dict)
    note: str = ""


CASES: Tuple[Case, ...] = (
    # R1 Product & Category Value
    Case("R1-category-all", "R1", "r1_product_category_value/category.sql",
         note="All categories, no filters"),
    Case("R1-category-dice", "R1", "r1_product_category_value/category.sql",
         {"year": "2025", "vehicle": "Motorcycle", "size_group": "Heavy"},
         "Slice 2025, dice Motorcycle x Heavy"),
    Case("R1-product-all", "R1", "r1_product_category_value/product.sql",
         {"top_n": "10"}, "Top 10 products in every category"),
    Case("R1-product-toys", "R1", "r1_product_category_value/product.sql",
         {"category": "Toys", "top_n": "10"}, "Drill into Toys"),
    # R2 Fleet, Courier & Rider Workload
    Case("R2-cube-all", "R2", "r2_fleet_courier_workload/courier_vehicle_cube.sql",
         note="Courier x vehicle CUBE, no filters"),
    Case("R2-pivot-orders", "R2", "r2_fleet_courier_workload/courier_vehicle_pivot.sql",
         {"measure": "orders"}, "Pivot, total orders"),
    Case("R2-pivot-per-rider-q1", "R2", "r2_fleet_courier_workload/courier_vehicle_pivot.sql",
         {"measure": "per_rider", "year": "2025", "quarter": "1"}, "Pivot per rider, 2025 Q1"),
    Case("R2-rider-top20", "R2", "r2_fleet_courier_workload/rider.sql",
         {"top_n": "20"}, "Top 20 riders, all period"),
    # R3 Customer Value Distribution
    Case("R3-deciles-all", "R3", "r3_customer_value_distribution/deciles.sql",
         note="Deciles, all customers"),
    Case("R3-deciles-dice", "R3", "r3_customer_value_distribution/deciles.sql",
         {"gender": "F", "year": "2025"}, "Deciles, female customers in 2025"),
    Case("R3-geo-country", "R3", "r3_customer_value_distribution/geography.sql",
         {"level": "country", "top_n": "20"}, "Top 20 countries x gender"),
    Case("R3-geo-city", "R3", "r3_customer_value_distribution/geography.sql",
         {"level": "city", "country": "Philippines", "top_n": "20"}, "Drill into Philippines cities"),
    Case("R3-customer-top20", "R3", "r3_customer_value_distribution/customer.sql",
         {"top_n": "20"}, "Top 20 customers"),
    # R4 Demand Calendar
    Case("R4-rollup-all", "R4", "r4_demand_calendar/rollup.sql",
         note="Year > Quarter > Month ROLLUP"),
    Case("R4-trend-month", "R4", "r4_demand_calendar/trend.sql",
         {"level": "month"}, "Monthly trend"),
    Case("R4-trend-day", "R4", "r4_demand_calendar/trend.sql",
         {"level": "day"}, "Daily trend, full year"),
    Case("R4-weekday-pivot", "R4", "r4_demand_calendar/weekday_pivot.sql",
         note="Month x weekday pivot"),
    Case("R4-busiest-days", "R4", "r4_demand_calendar/busiest_days.sql",
         {"top_n": "10"}, "Top 10 busiest days"),
)
