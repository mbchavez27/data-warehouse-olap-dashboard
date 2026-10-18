"""Report correctness: every report level against an independent reference.

Expected rows are computed in dwsupport.py from source_db (normalised the way
the ETL is specified to) and from the calendar rules, never from dw_db or the
report SQL. A level passes only when the API returns exactly the reference
rows, with the same values, rounding and order.

Three kinds of test:
  * TestReference*  - API output equals the reference for many filter sets
  * TestPinned      - hand-checked figures that do not depend on dwsupport.py
  * TestConsistency - totals, shares, ranks and subtotals agree with each other
"""
import unittest
from decimal import Decimal

import dwsupport as s

COLS = s.LEVEL_COLUMNS


class ReportCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s.preflight()

    def exact(self, rid, level, ref_rows, /, **filters):
        body = s.report(rid, level, **filters)
        problem = s.diff_rows(body["rows"], ref_rows, COLS[(rid, level)])
        self.assertIsNone(problem, "%s/%s %r: %s" % (rid, level, filters, problem))
        return body

    def ranked(self, rid, level, ref_all, order_col, id_col, limit, /, **filters):
        body = s.report(rid, level, **filters)
        problem = s.diff_tie_aware(body["rows"], ref_all, COLS[(rid, level)], order_col, id_col, limit)
        self.assertIsNone(problem, "%s/%s %r: %s" % (rid, level, filters, problem))
        return body


# ---------------------------------------------------------------------- R1

class TestReferenceR1(ReportCase):
    CATEGORY_CASES = [
        {}, {"year": 2024}, {"year": 2025}, {"quarter": 1}, {"quarter": 4, "year": 2024},
        {"year": 2024, "quarter": 4, "month": 12, "vehicle": "Car"},
        {"year": 2025, "vehicle": "Motorcycle", "size_group": "Heavy"},
        {"vehicle": "Trike"}, {"vehicle": "Bicycle", "size_group": "Light"},
        {"size_group": "Heavy"}, {"size_group": "Light"}, {"month": 9}, {"month": 2, "year": 2025},
    ]

    def test_category(self):
        for filters in self.CATEGORY_CASES:
            with self.subTest(filters=filters):
                self.exact("r1", "category", s.r1_category(**filters), **filters)

    PRODUCT_CASES = [
        {"category": "Toys", "top_n": 5}, {"category": "Laptops", "top_n": 3, "year": 2025},
        {"year": 2025, "quarter": 1, "vehicle": "Trike", "top_n": 3},
        {"category": "Men's Apparel", "size_group": "Heavy", "top_n": 4},
        {"category": "Bags", "month": 12, "year": 2024, "top_n": 2},
        {"top_n": 1}, {"category": "Makeup", "vehicle": "Car", "top_n": 6},
    ]

    def test_product(self):
        for filters in self.PRODUCT_CASES:
            with self.subTest(filters=filters):
                self.exact("r1", "product", s.r1_product(**filters), **filters)

    def test_product_default_is_top_10_per_category(self):
        body = s.report("r1", "product")
        per_cat = {}
        for row in body["rows"]:
            if not row["is_subtotal"]:
                per_cat[row["category"]] = per_cat.get(row["category"], 0) + 1
        self.assertEqual(sorted(per_cat), sorted(s.CATEGORIES))
        self.assertTrue(all(n == 10 for n in per_cat.values()), per_cat)
        self.exact("r1", "product", s.r1_product())


# ---------------------------------------------------------------------- R2

class TestReferenceR2(ReportCase):
    CUBE_CASES = [
        {}, {"year": 2024}, {"year": 2025, "quarter": 2}, {"year": 2024, "courier": "JNT", "age_band": "30-39"},
        {"courier": "FEDEZ", "age_band": "18-29"}, {"vehicle": "Car"}, {"size_group": "Heavy"},
        {"size_group": "Light", "year": 2025}, {"month": 12, "year": 2024}, {"age_band": "50-60", "vehicle": "Trike"},
    ]

    def test_cube(self):
        for filters in self.CUBE_CASES:
            with self.subTest(filters=filters):
                self.exact("r2", "courier_vehicle_cube", s.r2_cube(**filters), **filters)

    PIVOT_CASES = [
        {}, {"measure": "orders"}, {"measure": "per_rider"}, {"measure": "per_rider", "year": 2025, "size_group": "Light"},
        {"measure": "orders", "courier": "LBCD"}, {"measure": "per_rider", "age_band": "40-49"},
        {"measure": "orders", "vehicle": "Car", "quarter": 3}, {"measure": "per_rider", "month": 1, "year": 2025},
    ]

    def test_pivot(self):
        for filters in self.PIVOT_CASES:
            with self.subTest(filters=filters):
                self.exact("r2", "courier_vehicle_pivot", s.r2_pivot(**filters), **filters)

    RIDER_CASES = [
        {}, {"sort": "least"}, {"sort": "most", "top_n": 100}, {"sort": "least", "top_n": 100},
        {"sort": "least", "top_n": 20, "vehicle": "Car"}, {"year": 2025, "quarter": 2, "top_n": 10},
        {"courier": "JNT", "age_band": "30-39", "top_n": 50}, {"month": 2, "year": 2025, "top_n": 15},
        {"year": 2024, "sort": "least", "top_n": 5}, {"vehicle": "Trike", "top_n": 14},
    ]

    def test_rider(self):
        for filters in self.RIDER_CASES:
            with self.subTest(filters=filters):
                ref, limit = s.r2_rider(**filters)
                self.ranked("r2", "rider", ref, "orders", "rider", limit, **filters)

    def test_rider_least_keeps_the_busiest_first_rank_and_orders_ascending(self):
        # Rank is RANK() over descending orders, so ties share a rank; "least" only reverses the list.
        rows = s.report("r2", "rider", sort="least", top_n=100)["rows"]
        orders = [r["orders"] for r in rows]
        self.assertEqual(orders, sorted(orders))
        for r in rows:
            self.assertEqual(r["workload_rank"], 1 + sum(1 for o in orders if o > r["orders"]))


# ---------------------------------------------------------------------- R3

class TestReferenceR3(ReportCase):
    DECILE_CASES = [{}, {"gender": "F", "year": 2025}, {"gender": "M"}, {"year": 2024}, {"quarter": 3},
                    {"country": "Philippines"}, {"country": "Sudan", "gender": "F", "year": 2025}]

    def test_deciles(self):
        for filters in self.DECILE_CASES:
            with self.subTest(filters=filters):
                self.exact("r3", "deciles", s.r3_deciles(**filters), **filters)

    GEO_CASES = [{}, {"level": "country", "gender": "M"}, {"level": "country", "top_n": 5},
                 {"level": "country", "year": 2025, "quarter": 2},
                 {"level": "city", "country": "Philippines"}, {"level": "city", "country": "Sudan", "gender": "F"},
                 {"level": "city", "country": "Philippines", "top_n": 3, "year": 2024},
                 {"country": "Sudan"}]

    def test_geography(self):
        for filters in self.GEO_CASES:
            with self.subTest(filters=filters):
                self.exact("r3", "geography", s.r3_geography(**filters), **filters)

    CUSTOMER_CASES = [{"top_n": 20}, {}, {"top_n": 100}, {"country": "Philippines", "decile": 10, "top_n": 5},
                      {"gender": "F", "year": 2025, "top_n": 25}, {"country": "Sudan", "top_n": 50},
                      {"decile": 1, "top_n": 30}, {"quarter": 2, "decile": 5, "top_n": 10},
                      {"country": "Philippines", "city": "Canton"}, {"year": 2024, "gender": "M", "top_n": 15}]

    def test_customer(self):
        for filters in self.CUSTOMER_CASES:
            with self.subTest(filters=filters):
                ref, limit = s.r3_customer(**filters)
                self.ranked("r3", "customer", ref, "value", "customer", limit, **filters)


# ---------------------------------------------------------------------- R4

class TestReferenceR4(ReportCase):
    ROLLUP_CASES = [{}, {"year": 2024}, {"year": 2025}, {"year": 2024, "day_type": "weekend"},
                    {"day_type": "weekday"}, {"payday": "yes"}, {"payday": "no", "year": 2025},
                    {"vehicle": "Bicycle"}, {"size_group": "Heavy"}, {"vehicle": "Car", "size_group": "Light", "year": 2025}]

    def test_rollup(self):
        for filters in self.ROLLUP_CASES:
            with self.subTest(filters=filters):
                self.exact("r4", "rollup", s.r4_rollup(**filters), **filters)

    TREND_CASES = [{}, {"level": "year"}, {"level": "quarter"}, {"level": "month"}, {"level": "week"},
                   {"level": "day", "year": 2025, "payday": "yes"}, {"level": "day", "quarter": 4, "year": 2024},
                   {"level": "week", "quarter": 3, "vehicle": "Bicycle"}, {"level": "month", "day_type": "weekend"},
                   {"level": "quarter", "size_group": "Heavy"}, {"level": "day", "month": 2, "year": 2025},
                   {"level": "week", "year": 2025, "day_type": "weekday", "vehicle": "Car"},
                   {"level": "month", "payday": "no", "size_group": "Light"}]

    def test_trend(self):
        for filters in self.TREND_CASES:
            with self.subTest(filters=filters):
                self.exact("r4", "trend", s.r4_trend(**filters), **filters)

    PIVOT_CASES = [{}, {"year": 2025}, {"year": 2025, "vehicle": "Bicycle"}, {"quarter": 2}, {"payday": "yes"},
                   {"payday": "no", "size_group": "Heavy"}, {"year": 2024, "vehicle": "Trike"}]

    def test_weekday_pivot(self):
        for filters in self.PIVOT_CASES:
            with self.subTest(filters=filters):
                self.exact("r4", "weekday_pivot", s.r4_weekday_pivot(**filters), **filters)

    BUSY_CASES = [{}, {"sort": "quietest", "top_n": 3, "size_group": "Heavy"}, {"sort": "busiest", "top_n": 25},
                  {"sort": "quietest", "top_n": 20}, {"day_type": "weekend", "top_n": 10},
                  {"payday": "yes", "top_n": 40}, {"year": 2025, "quarter": 1, "top_n": 15},
                  {"vehicle": "Car", "sort": "quietest", "top_n": 8}, {"month": 12, "year": 2024, "top_n": 31},
                  {"day_type": "weekday", "payday": "no", "top_n": 12}]

    def test_busiest_days(self):
        for filters in self.BUSY_CASES:
            with self.subTest(filters=filters):
                ref_all = s.r4_busiest_days(**dict(filters, top_n=10 ** 6))
                self.ranked("r4", "busiest_days", ref_all, "orders", "date",
                            int(filters.get("top_n") or 10), **filters)


# ------------------------------------------------------------ pinned figures

class TestPinned(ReportCase):
    """Figures checked by hand against source_db. They do not use dwsupport's models."""

    def test_headline_totals_equal_the_source(self):
        cat = s.report("r1", "category")["rows"][-1]
        self.assertEqual((cat["category"], cat["units"], cat["value"], cat["value_share_pct"]),
                         ("All categories", 10999917, 54847773792.91, 100.0))
        cube = s.report("r2", "courier_vehicle_cube")["rows"][-1]
        self.assertEqual((cube["orders"], cube["units"], cube["riders"], cube["orders_per_rider"]),
                         (1000000, 10999917, 100, 10000))
        geo = s.report("r3", "geography")["rows"][-3]
        self.assertEqual((geo["location"], geo["customers"], geo["orders"], geo["value"]),
                         ("All locations", 99996, 1000000, 54847773792.91))
        roll = s.report("r4", "rollup")["rows"][-1]
        self.assertEqual((roll["hierarchy_level"], roll["days"], roll["orders"], roll["units"]),
                         ("all", 365, 1000000, 10999917))

    def test_toys_is_the_top_category(self):
        rows = s.report("r1", "category")["rows"]
        self.assertEqual((rows[0]["category"], rows[0]["units"], rows[0]["value"], rows[0]["value_share_pct"],
                          rows[0]["value_rank"]), ("Toys", 2383459, 12007769864.06, 21.9, 1))

    def test_filters_narrow_the_totals_to_source_figures(self):
        total = s.report("r1", "category", year=2025, vehicle="Car")["rows"][-1]
        self.assertEqual((total["units"], total["value"]), (1203207, 5998869761.03))
        heavy = s.report("r1", "category", size_group="Heavy")["rows"][-1]
        self.assertEqual(heavy["units"], 7732614)

    def test_fedez_fleet(self):
        rows = {(r["courier"], r["vehicle"]): r for r in s.report("r2", "courier_vehicle_cube")["rows"]}
        self.assertEqual(rows[("FEDEZ", "Car")]["orders"], 60165)
        self.assertEqual(rows[("FEDEZ", "Bicycle")]["orders"], 90245)
        self.assertEqual(rows[("FEDEZ", "Bicycle")]["riders"], 9)
        self.assertEqual(rows[("FEDEZ", "Car")]["units"], 663038)

    def test_top_customers(self):
        rows = s.report("r3", "customer", top_n=3)["rows"]
        self.assertEqual([(r["customer"], r["value"]) for r in rows],
                         [("dgILKyVRFR", 1942958.73), ("homlvVOlHw", 1662806.12), ("figVhsqVXs", 1646875.90)])
        self.assertEqual([r["value_rank"] for r in rows], [1, 2, 3])

    def test_sudan_is_the_top_country(self):
        row = s.report("r3", "geography")["rows"][0]
        self.assertEqual((row["location"], row["gender"], row["customers"], row["orders"], row["value"],
                          row["value_rank"]), ("Sudan", "All", 444, 4561, 250790043.45, 1))

    def test_busiest_and_quietest_days(self):
        top = s.report("r4", "busiest_days", top_n=1)["rows"][0]
        self.assertEqual((top["date"], top["day_name"], top["orders"], top["is_payday"], top["is_weekend"]),
                         ("2025-03-14", "Friday", 2888, False, False))
        quiet = s.report("r4", "busiest_days", sort="quietest", top_n=1)["rows"][0]
        self.assertEqual((quiet["date"], quiet["orders"], quiet["demand_rank"]), ("2025-03-18", 2588, 365))

    def test_orders_by_year(self):
        rows = {(r["hierarchy_level"], r["year"]): r for r in s.report("r4", "rollup")["rows"]}
        self.assertEqual(rows[("year", 2024)]["orders"], 271594)
        self.assertEqual(rows[("year", 2025)]["orders"], 728406)
        self.assertEqual((rows[("year", 2024)]["days"], rows[("year", 2025)]["days"]), (99, 266))

    def test_first_month_is_a_partial_september(self):
        first = s.report("r4", "trend", level="month")["rows"][0]
        self.assertEqual((first["period_label"], first["period_start"], first["days"], first["orders"]),
                         ("2024 September", "2024-09-24", 7, 19137))

    def test_pinned_values_agree_with_source_db_directly(self):
        # The same numbers, asked of source_db with SQL written for this test.
        self.assertEqual(s.src_scalar(
            """SELECT count(*) FROM "Orders" WHERE (CASE WHEN "deliveryDate" ~ '^\\d{4}-'
               THEN to_date("deliveryDate",'YYYY-MM-DD') ELSE to_date("deliveryDate",'MM/DD/YYYY') END)
               = DATE '2025-03-14'"""), "2888")
        self.assertEqual(s.src_scalar(
            """SELECT sum(oi.quantity) FROM "OrderItems" oi JOIN "Products" p ON p.id = oi."ProductId"
               WHERE lower(trim(p.category)) IN ('toy','toys')"""), "2383459")
        self.assertEqual(s.src_scalar(
            """SELECT round(sum(oi.quantity * round(p.price::numeric, 2)), 2) FROM "OrderItems" oi
               JOIN "Products" p ON p.id = oi."ProductId" """), "54847773792.91")


# ------------------------------------------------------------ consistency

class TestConsistency(ReportCase):
    def close(self, a, b, tol):
        self.assertLessEqual(abs(a - b), tol, "%s vs %s" % (a, b))

    def test_r1_category_parts_sum_to_total(self):
        for filters in ({}, {"year": 2025}, {"vehicle": "Car", "size_group": "Heavy"}):
            with self.subTest(filters=filters):
                rows = s.report("r1", "category", **filters)["rows"]
                parts, total = rows[:-1], rows[-1]
                self.assertTrue(total["is_total"])
                self.assertTrue(all(not r["is_total"] for r in parts))
                self.assertEqual(sum(r["units"] for r in parts), total["units"])
                self.close(sum(Decimal(str(r["value"])) for r in parts), Decimal(str(total["value"])), Decimal("0.001"))
                self.close(sum(Decimal(str(r["value_share_pct"])) for r in parts), Decimal(100), Decimal("0.5"))
                values = [r["value"] for r in parts]
                self.assertEqual(values, sorted(values, reverse=True))
                self.assertEqual([r["value_rank"] for r in parts], list(range(1, len(parts) + 1)))

    def test_r1_product_subtotal_covers_all_products(self):
        rows = s.report("r1", "product", category="Toys", top_n=3)["rows"]
        parts, sub = rows[:-1], rows[-1]
        self.assertTrue(sub["is_subtotal"])
        self.assertEqual(len(parts), 3)
        self.assertLess(sum(r["units"] for r in parts), sub["units"], "subtotal should cover more than the top 3")
        cat_total = [r for r in s.report("r1", "category")["rows"] if r["category"] == "Toys"][0]
        self.assertEqual((sub["units"], sub["value"]), (cat_total["units"], cat_total["value"]))

    def test_r2_cube_levels_add_up(self):
        for filters in ({}, {"year": 2025, "size_group": "Heavy"}, {"courier": "JNT"}):
            with self.subTest(filters=filters):
                rows = s.report("r2", "courier_vehicle_cube", **filters)["rows"]
                by = {}
                for r in rows:
                    by.setdefault(r["grouping_level"], []).append(r)
                grand = by[3][0]
                self.assertEqual(len(by[3]), 1)
                for level in (0, 1, 2):
                    self.assertEqual(sum(r["orders"] for r in by[level]), grand["orders"], "level %d" % level)
                    self.assertEqual(sum(r["units"] for r in by[level]), grand["units"], "level %d" % level)
                for sub in by[1]:
                    cells = [r for r in by[0] if r["courier"] == sub["courier"]]
                    self.assertEqual(sum(r["orders"] for r in cells), sub["orders"])
                    self.assertEqual(sum(r["riders"] for r in cells), sub["riders"])
                self.assertEqual(sum(r["riders"] for r in by[0]), grand["riders"])
                self.assertEqual(grand["order_share_pct"], 100.0)
                self.close(sum(Decimal(str(r["order_share_pct"])) for r in by[0]), Decimal(100), Decimal("1"))

    def test_r2_pivot_totals(self):
        for measure in ("orders", "per_rider"):
            for filters in ({}, {"year": 2025}):
                with self.subTest(measure=measure, filters=filters):
                    rows = s.report("r2", "courier_vehicle_pivot", measure=measure, **filters)["rows"]
                    self.assertTrue(rows[-1]["is_total"])
                    self.assertEqual(rows[-1]["courier"], "All couriers")
                    self.assertEqual([r["courier"] for r in rows[:-1]], sorted(r["courier"] for r in rows[:-1]))
                    self.assertEqual(sum(r["riders"] for r in rows[:-1]), rows[-1]["riders"])
                    if measure == "orders":
                        for col in ("motorcycle", "bicycle", "car", "trike", "total"):
                            self.assertEqual(sum(r[col] for r in rows[:-1]), rows[-1][col], col)
                        for r in rows:
                            self.assertEqual(r["motorcycle"] + r["bicycle"] + r["car"] + r["trike"], r["total"])

    def test_r2_rider_statistics(self):
        rows = s.report("r2", "rider", top_n=100)["rows"]
        self.assertEqual(len(rows), 100)
        self.assertEqual(sum(r["orders"] for r in rows), 1000000)
        self.assertEqual(sum(r["units"] for r in rows), 10999917)
        self.assertEqual(len({r["rider"] for r in rows}), 100)
        self.assertEqual([r["workload_rank"] for r in rows[:3]], [1, 2, 3])
        for r in rows:
            self.assertLessEqual(r["active_days"], r["calendar_days"])
            self.assertEqual(r["calendar_days"], 365)
            self.assertGreaterEqual(r["workload_percentile"], 0)
            self.assertLessEqual(r["workload_percentile"], 100)
            self.assertIn(r["vehicle"], s.VEHICLES)
            self.assertIn(r["courier"], s.COURIERS)
        self.assertEqual(rows[0]["workload_percentile"], 100.0)
        self.assertEqual(rows[-1]["workload_percentile"], 0.0)

    def test_r3_deciles_cover_every_buyer_once(self):
        rows = s.report("r3", "deciles")["rows"]
        self.assertEqual([r["decile"] for r in rows], list(range(1, 11)))
        self.assertEqual(sum(r["customers"] for r in rows), 99996)
        self.assertEqual(rows[-1]["cumulative_share_pct"], 100.0)
        self.close(sum(Decimal(str(r["value_share_pct"])) for r in rows), Decimal(100), Decimal("0.5"))
        for upper, lower in zip(rows, rows[1:]):
            self.assertGreaterEqual(upper["min_customer_value"], lower["max_customer_value"])
            self.assertGreater(upper["avg_value_per_customer"], lower["avg_value_per_customer"])
        for r in rows:
            self.assertLessEqual(r["min_customer_value"], r["avg_value_per_customer"])
            self.assertLessEqual(r["avg_value_per_customer"], r["max_customer_value"])

    def test_r3_geography_genders_add_up_to_each_location(self):
        rows = s.report("r3", "geography", level="country")["rows"]
        ranked = [r for r in rows if r["grouping_level"] in (0, 1)]
        locations = {}
        for r in ranked:
            locations.setdefault(r["location"], []).append(r)
        self.assertEqual(len(locations), 20)
        for loc, parts in locations.items():
            total = [r for r in parts if r["grouping_level"] == 1]
            cells = [r for r in parts if r["grouping_level"] == 0]
            self.assertEqual(len(total), 1, loc)
            self.assertEqual(sum(r["customers"] for r in cells), total[0]["customers"], loc)
            self.assertEqual(sum(r["orders"] for r in cells), total[0]["orders"], loc)
            self.close(sum(Decimal(str(r["value"])) for r in cells), Decimal(str(total[0]["value"])), Decimal("0.001"))
        ranks = [locations[k][0]["value_rank"] for k in locations]
        self.assertEqual(ranks, sorted(ranks))
        level2 = [r for r in rows if r["grouping_level"] == 2]
        level3 = [r for r in rows if r["grouping_level"] == 3]
        self.assertEqual(sum(r["customers"] for r in level2), level3[0]["customers"])
        self.assertEqual(sum(r["orders"] for r in level2), level3[0]["orders"])

    def test_r3_customer_metrics_are_internally_consistent(self):
        rows = s.report("r3", "customer", top_n=100)["rows"]
        self.assertEqual([r["value_rank"] for r in rows], list(range(1, 101)))
        values = [r["value"] for r in rows]
        self.assertEqual(values, sorted(values, reverse=True))
        for r in rows:
            self.close(Decimal(str(r["avg_order_value"])), Decimal(str(r["value"])) / r["orders"], Decimal("0.01"))
            self.assertEqual(r["decile"], 1)
            self.assertIn(r["gender"], ("F", "M"))

    def test_r4_rollup_levels_add_up(self):
        for filters in ({}, {"payday": "yes"}, {"vehicle": "Motorcycle", "size_group": "Heavy"}):
            with self.subTest(filters=filters):
                rows = s.report("r4", "rollup", **filters)["rows"]
                by = {}
                for r in rows:
                    by.setdefault(r["hierarchy_level"], []).append(r)
                allrow = by["all"][0]
                for level in ("month", "quarter", "year"):
                    for col in ("days", "orders", "units"):
                        self.assertEqual(sum(r[col] for r in by[level]), allrow[col], "%s %s" % (level, col))

    def test_r4_trend_day_level_matches_busiest_days(self):
        days = {r["period_label"]: r["orders"] for r in s.report("r4", "trend", level="day")["rows"]}
        self.assertEqual(len(days), 365)
        self.assertEqual(sum(days.values()), 1000000)
        for row in s.report("r4", "busiest_days", top_n=25)["rows"]:
            self.assertEqual(days[row["date"]], row["orders"])

    def test_r4_trend_levels_agree_with_each_other(self):
        totals = {}
        for level in ("year", "quarter", "month", "week", "day"):
            rows = s.report("r4", "trend", level=level)["rows"]
            totals[level] = (sum(r["days"] for r in rows), sum(r["orders"] for r in rows), sum(r["units"] for r in rows))
            starts = [r["period_start"] for r in rows]
            self.assertEqual(starts, sorted(starts), level)
            self.assertIsNone(rows[0]["change_vs_previous_pct"], level)
        self.assertEqual(set(totals.values()), {(365, 1000000, 10999917)})

    def test_r4_weekday_pivot_matches_trend(self):
        rows = s.report("r4", "weekday_pivot")["rows"]
        self.assertEqual(rows[-1]["month_label"], "All months")
        self.assertTrue(rows[-1]["is_total"])
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[-1]["all_days"], 2739.7)

    def test_r4_busiest_days_ranks_and_flags(self):
        rows = s.report("r4", "busiest_days", top_n=60)["rows"]
        self.assertEqual([r["orders"] for r in rows], sorted((r["orders"] for r in rows), reverse=True))
        for r in rows:
            self.assertEqual(r["is_weekend"], r["day_name"] in ("Saturday", "Sunday"))
        quiet = s.report("r4", "busiest_days", sort="quietest", top_n=60)["rows"]
        self.assertEqual([r["orders"] for r in quiet], sorted(r["orders"] for r in quiet))
        self.assertGreater(rows[-1]["orders"], quiet[-1]["orders"])


if __name__ == "__main__":
    unittest.main()
