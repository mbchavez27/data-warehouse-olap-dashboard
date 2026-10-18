"""API contract: health, catalog, metadata endpoints, status codes and filter validation.

These checks need no reference data. They pin down what a client of the
dashboard relies on: which levels exist, which columns each returns, which
requests are refused, and that user text is bound as a value, not as SQL.
"""
import unittest

import dwsupport as s


class ContractCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s.preflight()


class TestHealthAndCatalog(ContractCase):
    def test_health(self):
        status, body = s.api_get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"database": "ok", "status": "ok"})

    def test_catalog_lists_four_reports_and_twelve_levels(self):
        status, body = s.api_get(s.REPORTS)
        self.assertEqual(status, 200)
        reports = {r["id"]: r for r in body["reports"]}
        self.assertEqual(sorted(reports), ["r1", "r2", "r3", "r4"])
        expected = {}
        for (rid, level), cols in s.LEVEL_COLUMNS.items():
            expected.setdefault(rid, {})[level] = cols
        for rid, levels in expected.items():
            got = {lv["id"]: [c if isinstance(c, str) else c["name"] for c in lv["columns"]]
                   for lv in reports[rid]["levels"]}
            self.assertEqual(got, levels, "levels/columns of %s in the catalog" % rid)
        self.assertEqual(sum(len(r["levels"]) for r in reports.values()), 12)

    def test_every_level_returns_the_cataloged_columns_in_order(self):
        for (rid, level), cols in s.LEVEL_COLUMNS.items():
            with self.subTest(level="%s/%s" % (rid, level)):
                body = s.report(rid, level)
                self.assertEqual([c["name"] for c in body["columns"]], cols)
                self.assertEqual(body["report"], rid)
                self.assertEqual(body["level"], level)
                self.assertEqual(body["rowCount"], len(body["rows"]))
                self.assertGreater(body["rowCount"], 0)
                for row in body["rows"]:
                    self.assertEqual(set(row), set(cols))

    def test_level_aliases_return_the_same_rows(self):
        for alias, full in (("cube", "courier_vehicle_cube"), ("pivot", "courier_vehicle_pivot")):
            with self.subTest(alias=alias):
                a = s.report("r2", alias)["rows"]
                b = s.report("r2", full)["rows"]
                self.assertEqual(a, b)

    def test_repeat_calls_are_deterministic(self):
        for rid, level, filters in (("r3", "customer", {"top_n": 15}), ("r4", "busiest_days", {}),
                                    ("r2", "rider", {"sort": "least"})):
            with self.subTest(level="%s/%s" % (rid, level)):
                status1, a = s.api_get("%s/%s/%s" % (s.REPORTS, rid, level), **filters)
                status2, b = s.api_get("%s/%s/%s" % (s.REPORTS, rid, level), **filters)
                self.assertEqual((status1, status2), (200, 200))
                self.assertEqual(a["rows"], b["rows"])

    def test_response_echoes_the_filters_it_applied(self):
        body = s.report("r1", "category", year=2025, vehicle="Car")
        self.assertEqual(body["params"]["year"], "2025")
        self.assertEqual(body["params"]["vehicle"], "Car")
        self.assertEqual(body["params"]["quarter"], "")


class TestMetadataEndpoints(ContractCase):
    def test_dimensions_lists_the_canonical_values(self):
        status, body = s.api_get("/api/dimensions")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(body["categories"]), sorted(s.CATEGORIES))
        self.assertEqual(sorted(body["ageBands"]), ["18-29", "30-39", "40-49", "50-60"])
        countries = s.dw("""SELECT DISTINCT country FROM "DIM_GEOGRAPHY" WHERE "geoKey" <> 0 ORDER BY 1""")
        self.assertEqual(sorted(body["countries"]), sorted(c[0] for c in countries))
        self.assertEqual(len(set(body["countries"])), len(body["countries"]), "duplicate countries")

    def test_cities_for_a_country_match_the_warehouse(self):
        status, body = s.api_get("/api/dimensions/cities", country="Philippines")
        self.assertEqual(status, 200)
        cities = s.dw("""SELECT DISTINCT city FROM "DIM_GEOGRAPHY"
                         WHERE country = 'Philippines' AND "geoKey" <> 0""")
        self.assertEqual(sorted(body["cities"]), sorted(c[0] for c in cities))
        self.assertEqual(len(body["cities"]), 412)

    def test_cities_requires_a_country(self):
        status, _ = s.api_get("/api/dimensions/cities")
        self.assertEqual(status, 400)


class TestErrorHandling(ContractCase):
    def assertStatus(self, want, path, **filters):
        status, body = s.api_get(path, **filters)
        self.assertEqual(status, want, "%s %r -> %s %s" % (path, filters, status, ascii(body)[:200]))
        return body

    def test_unknown_report_and_level_are_404(self):
        self.assertStatus(404, s.REPORTS + "/r9/category")
        self.assertStatus(404, s.REPORTS + "/r1/nope")
        self.assertStatus(404, s.REPORTS + "/r4/category")

    def test_invalid_filters_are_400_with_a_message_and_no_columns(self):
        cases = [
            ("r1/category", {"bogus": 1}), ("r1/category", {"year": 2023}),
            ("r1/category", {"year": "abc"}), ("r1/category", {"quarter": 5}),
            ("r1/category", {"quarter": 0}), ("r1/category", {"month": 13}),
            ("r1/category", {"vehicle": "Bike"}), ("r1/category", {"size_group": "Huge"}),
            ("r1/product", {"top_n": 0}), ("r1/product", {"top_n": 1001}),
            ("r1/product", {"top_n": "x"}),
            ("r2/rider", {"sort": "up"}), ("r2/rider", {"age_band": "20-25"}),
            ("r2/courier_vehicle_pivot", {"measure": "avg"}),
            ("r2/courier_vehicle_cube", {"courier": "UPS"}),
            ("r3/deciles", {"decile": 3}), ("r3/customer", {"decile": 11}),
            ("r3/customer", {"decile": 0}), ("r3/geography", {"level": "street"}),
            ("r3/geography", {"level": "city"}),
            ("r3/customer", {"city": "Canton"}),  # city names repeat across countries
            ("r3/deciles", {"gender": "X"}),
            ("r4/trend", {"level": "century"}), ("r4/trend", {"top_n": 5}),
            ("r4/rollup", {"hierarchy": "x"}), ("r4/rollup", {"quarter": 1}),
            ("r4/busiest_days", {"sort": "median"}), ("r4/busiest_days", {"day_type": "holiday"}),
            ("r4/weekday_pivot", {"payday": "maybe"}),
        ]
        for path, filters in cases:
            with self.subTest(path=path, filters=filters):
                body = self.assertStatus(400, "%s/%s" % (s.REPORTS, path), **filters)
                self.assertTrue(body.get("error"), "400 without an error message")
                self.assertNotIn("columns", body)
                self.assertNotIn("rows", body)

    def test_every_documented_enum_value_is_accepted(self):
        accepted = [
            ("r1/category", {"year": 2024}), ("r1/category", {"year": 2025}),
            ("r1/category", {"quarter": 1}), ("r1/category", {"quarter": 4}),
            ("r1/category", {"month": 1}), ("r1/category", {"month": 12}),
            ("r1/product", {"top_n": 1}), ("r1/product", {"top_n": 1000}),
            ("r2/rider", {"sort": "most"}), ("r2/rider", {"sort": "least"}),
            ("r2/courier_vehicle_pivot", {"measure": "orders"}),
            ("r2/courier_vehicle_pivot", {"measure": "per_rider"}),
            ("r3/customer", {"decile": 1}), ("r3/customer", {"decile": 10}),
            ("r3/geography", {"level": "country"}),
            ("r3/geography", {"level": "city", "country": "Philippines"}),
            ("r3/deciles", {"gender": "F"}), ("r3/deciles", {"gender": "M"}),
            ("r4/trend", {"level": "year"}), ("r4/trend", {"level": "quarter"}),
            ("r4/trend", {"level": "month"}), ("r4/trend", {"level": "week"}),
            ("r4/trend", {"level": "day", "quarter": 1}),
            ("r4/busiest_days", {"sort": "busiest"}), ("r4/busiest_days", {"sort": "quietest"}),
            ("r4/busiest_days", {"day_type": "weekday"}), ("r4/busiest_days", {"day_type": "weekend"}),
            ("r4/busiest_days", {"payday": "yes"}), ("r4/busiest_days", {"payday": "no"}),
        ]
        for vehicle in s.VEHICLES:
            accepted.append(("r1/category", {"vehicle": vehicle}))
        for group in s.SIZE_GROUPS:
            accepted.append(("r1/category", {"size_group": group}))
        for courier in s.COURIERS:
            accepted.append(("r2/courier_vehicle_cube", {"courier": courier}))
        for band in ("18-29", "30-39", "40-49", "50-60"):
            accepted.append(("r2/rider", {"age_band": band}))
        for category in s.CATEGORIES:
            accepted.append(("r1/product", {"category": category, "top_n": 1}))
        for path, filters in accepted:
            with self.subTest(path=path, filters=filters):
                body = self.assertStatus(200, "%s/%s" % (s.REPORTS, path), **filters)
                self.assertEqual(body["rowCount"], len(body["rows"]))

    def test_free_text_filters_with_no_match_return_zero_rows(self):
        # The catalog declares category/country/city as free text, not enums, so an
        # unknown value is a valid request that matches nothing.
        for path, filters in (("r1/product", {"category": "Nope"}),
                              ("r3/customer", {"country": "Atlantis"}),
                              ("r3/customer", {"country": "Philippines", "city": "Nowhere"})):
            with self.subTest(path=path, filters=filters):
                body = self.assertStatus(200, "%s/%s" % (s.REPORTS, path), **filters)
                self.assertEqual(body["rowCount"], 0)

    def test_declared_enum_values_match_the_validation(self):
        status, cat = s.api_get(s.REPORTS)
        self.assertEqual(status, 200)
        checked = 0
        for report in cat["reports"]:
            for level in report["levels"]:
                for p in level["params"]:
                    if p["kind"] != "enum":
                        continue
                    path = "%s/%s/%s" % (s.REPORTS, report["id"], level["id"])
                    extra = {"country": "Philippines"} if (report["id"], level["id"]) == ("r3", "geography") else {}
                    for value in p["values"]:
                        st, _ = s.api_get(path, **dict(extra, **{p["name"]: value}))
                        self.assertEqual(st, 200, "%s %s=%s" % (path, p["name"], value))
                        checked += 1
                    st, _ = s.api_get(path, **{p["name"]: "definitely-not-a-value"})
                    self.assertEqual(st, 400, "%s %s=<bad>" % (path, p["name"]))
        self.assertGreater(checked, 40)

    def test_post_is_not_a_report_route(self):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(s.API_ROOT + s.REPORTS + "/r1/category", data=b"{}", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
        except urllib.error.HTTPError as err:
            status = err.code
        self.assertIn(status, (404, 405))

    def test_sql_looking_text_is_bound_as_a_value(self):
        injection = "x' OR '1'='1"
        for path in ("r3/customer", "r3/deciles", "r3/geography"):
            with self.subTest(path=path):
                status, body = s.api_get("%s/%s" % (s.REPORTS, path), country=injection)
                self.assertEqual(status, 200)
                self.assertEqual(body["params"]["country"], injection)
                data_rows = [r for r in body["rows"] if r.get("grouping_level") not in (2, 3)]
                self.assertEqual(data_rows, [], "the text matched real rows")
        status, body = s.api_get("/api/dimensions/cities", country="'; DROP TABLE \"DIM_DATE\"; --")
        self.assertEqual(status, 200)
        self.assertEqual(body["cities"], [])
        self.assertEqual(s.dw_scalar('SELECT count(*) FROM "DIM_DATE"'), "365")

    def test_not_found_for_unknown_route(self):
        status, _ = s.api_get("/api/nothing-here")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
