"""Warehouse integrity: the loaded dw_db against itself and against source_db.

The report tests compare API output with a reference built from source_db, so
a wrong warehouse would already fail them. These tests say *where* it is wrong:
a calendar attribute, a key, a band, a summary view, or a lost row.
"""
import datetime
import unittest

import dwsupport as s


class IntegrityCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s.preflight()

    def assertZero(self, sql, what):
        got = s.dw_scalar(sql)
        self.assertEqual(got, "0", "%s: %s violations" % (what, got))


class TestDimensions(IntegrityCase):
    def test_dim_date_is_the_365_day_calendar_with_correct_attributes(self):
        rows = s.dw("""SELECT "dateKey", "fullDate", "dayOfMonth", "dayName", "isWeekend", "isPayDay",
                              "weekOfYear", "monthNumber", "monthName", quarter, year
                       FROM "DIM_DATE" ORDER BY "fullDate" """)
        self.assertEqual(len(rows), 365)
        for row, d in zip(rows, s.CAL):
            info = s.dateinfo(d)
            want = [d.strftime("%Y%m%d"), d.isoformat(), str(d.day), info.day_name,
                    "t" if info.weekend else "f", "t" if info.payday else "f", str(info.week),
                    str(d.month), info.month_name, str(info.quarter), str(d.year)]
            self.assertEqual([c.strip() for c in row], want, "DIM_DATE row for %s" % d)

    def test_unknown_member_rows(self):
        for table, key in (("DIM_CUSTOMER", "customerKey"), ("DIM_GEOGRAPHY", "geoKey"),
                           ("DIM_PRODUCT", "productKey"), ("DIM_RIDER", "riderKey"),
                           ("DIM_ORDERSIZE", "orderSizeKey")):
            with self.subTest(table=table):
                self.assertEqual(s.dw_scalar('SELECT count(*) FROM "%s" WHERE "%s" = 0' % (table, key)), "1")

    def test_dimension_row_counts_match_source(self):
        pairs = (("DIM_CUSTOMER", '"Users"'), ("DIM_PRODUCT", '"Products"'), ("DIM_RIDER", '"Riders"'))
        for dim, source in pairs:
            with self.subTest(dim=dim):
                n_dw = int(s.dw_scalar('SELECT count(*) FROM "%s"' % dim)) - 1
                n_src = int(s.src_scalar("SELECT count(*) FROM %s" % source))
                self.assertEqual(n_dw, n_src)

    def test_order_size_bands(self):
        rows = s.dw("""SELECT "orderSizeKey", "sizeName", "sizeGroup", "minQuantity", "maxQuantity"
                       FROM "DIM_ORDERSIZE" ORDER BY 1""")
        self.assertEqual(rows, [["0", "Unknown", "Unknown", "0", "0"], ["1", "Small", "Light", "1", "6"],
                                ["2", "Medium", "Light", "7", "10"], ["3", "Large", "Heavy", "11", "15"],
                                ["4", "Bulk", "Heavy", "16", "2147483647"]])

    def test_categories_vehicles_and_genders_are_canonical(self):
        cats = [r[0] for r in s.dw('SELECT DISTINCT category FROM "DIM_PRODUCT" WHERE "productKey" <> 0')]
        self.assertEqual(sorted(cats), sorted(s.CATEGORIES))
        vehicles = dict(s.dw("""SELECT "vehicleType", count(*) FROM "DIM_RIDER" WHERE "riderKey" <> 0
                                GROUP BY 1"""))
        self.assertEqual(vehicles, {"Bicycle": "29", "Motorcycle": "42", "Car": "15", "Trike": "14"})
        genders = [r[0] for r in s.dw('SELECT DISTINCT gender FROM "DIM_CUSTOMER" WHERE "customerKey" <> 0')]
        self.assertEqual(sorted(genders), ["F", "M"])

    def test_riders_match_source_attribute_by_attribute(self):
        got = {int(r[0]): (r[1], r[2], r[3], int(r[4]), r[5]) for r in s.dw(
            """SELECT "riderId", "fullName", "courierName", "vehicleType", age, "ageBand"
               FROM "DIM_RIDER" WHERE "riderKey" <> 0""")}
        want = {r.id: (r.name, r.courier, r.vehicle, r.age, r.band) for r in s.riders().values()}
        self.assertEqual(got, want)

    def test_customers_and_geography_match_source(self):
        got = {}
        for cid, username, gender, country, city in s.dw(
                """SELECT DISTINCT c."customerId", c.username, c.gender, g.country, g.city
                   FROM "FACT_ORDERDELIVERY" f
                   JOIN "DIM_CUSTOMER" c ON c."customerKey" = f."customerKey"
                   JOIN "DIM_GEOGRAPHY" g ON g."geoKey" = f."geoKey" """):
            got[int(cid)] = (username, gender, country, city)
        user_map = s.users()
        buyers = {o.user for o in s.orders()}
        self.assertEqual(set(got), buyers)
        for uid in buyers:
            u = user_map[uid]
            self.assertEqual(got.get(uid), (u.username, u.gender, u.country, u.city), "customer %s" % uid)


class TestFacts(IntegrityCase):
    def test_no_orphan_or_unknown_keys_in_the_facts(self):
        joins = {
            "FACT_ORDERITEM": [("deliveryDateKey", "DIM_DATE", "dateKey"), ("riderKey", "DIM_RIDER", "riderKey"),
                               ("geoKey", "DIM_GEOGRAPHY", "geoKey"), ("orderSizeKey", "DIM_ORDERSIZE", "orderSizeKey"),
                               ("customerKey", "DIM_CUSTOMER", "customerKey"), ("productKey", "DIM_PRODUCT", "productKey")],
            "FACT_ORDERDELIVERY": [("deliveryDateKey", "DIM_DATE", "dateKey"), ("riderKey", "DIM_RIDER", "riderKey"),
                                   ("geoKey", "DIM_GEOGRAPHY", "geoKey"),
                                   ("orderSizeKey", "DIM_ORDERSIZE", "orderSizeKey"),
                                   ("customerKey", "DIM_CUSTOMER", "customerKey")],
            "FACT_RIDERDAILY": [("dateKey", "DIM_DATE", "dateKey"), ("riderKey", "DIM_RIDER", "riderKey")],
        }
        for fact, keys in joins.items():
            for col, dim, dim_col in keys:
                with self.subTest(fact=fact, key=col):
                    self.assertZero('SELECT count(*) FROM "%s" f LEFT JOIN "%s" d ON d."%s" = f."%s" '
                                    'WHERE d."%s" IS NULL' % (fact, dim, dim_col, col, dim_col), "orphan keys")
                    if dim != "DIM_DATE":
                        self.assertZero('SELECT count(*) FROM "%s" WHERE "%s" = 0' % (fact, col), "unknown members")

    def test_grain_is_unique(self):
        self.assertZero("""SELECT count(*) FROM (SELECT 1 FROM "FACT_ORDERITEM"
                           GROUP BY "orderNumber", "productKey" HAVING count(*) > 1) x""", "duplicate order lines")
        self.assertZero("""SELECT count(*) - count(DISTINCT "orderNumber") FROM "FACT_ORDERDELIVERY" """,
                        "duplicate deliveries")
        self.assertZero("""SELECT count(*) FROM (SELECT 1 FROM "FACT_RIDERDAILY"
                           GROUP BY "dateKey", "riderKey" HAVING count(*) > 1) x""", "duplicate rider-days")

    def test_row_counts_and_totals_reconcile_with_source(self):
        src_orders = s.orders()
        n_orders = len(src_orders)
        n_units = sum(o.units for o in src_orders)
        n_cents = sum(o.cents for o in src_orders)
        n_lines = int(s.src_scalar('SELECT count(*) FROM "OrderItems"'))
        self.assertEqual(int(s.dw_scalar('SELECT count(*) FROM "FACT_ORDERDELIVERY"')), n_orders)
        self.assertEqual(int(s.dw_scalar('SELECT count(*) FROM "FACT_ORDERITEM"')), n_lines)
        units, cents = s.dw('SELECT sum(quantity), (sum("lineValue") * 100)::bigint FROM "FACT_ORDERITEM"')[0]
        self.assertEqual(int(units), n_units)
        self.assertEqual(int(cents), n_cents)
        self.assertEqual(int(s.dw_scalar('SELECT sum("totalQuantity") FROM "FACT_ORDERDELIVERY"')), n_units)
        self.assertEqual(s.dw('SELECT sum("ordersDelivered"), sum("itemsDelivered") FROM "FACT_RIDERDAILY"')[0],
                         [str(n_orders), str(n_units)])

    def test_every_source_order_is_in_the_warehouse_on_the_right_day_rider_and_customer(self):
        got = {}
        for number, datekey, rider_id, cust_id, qty, lines, size in s.dw(
                """SELECT f."orderNumber", f."deliveryDateKey", r."riderId", c."customerId",
                          f."totalQuantity", f."lineItemCount", f."orderSizeKey"
                   FROM "FACT_ORDERDELIVERY" f
                   JOIN "DIM_RIDER" r ON r."riderKey" = f."riderKey"
                   JOIN "DIM_CUSTOMER" c ON c."customerKey" = f."customerKey" """):
            got[number] = (int(datekey), int(rider_id), int(cust_id), int(qty), int(size))
        mismatches = []
        for o in s.orders():
            band = 1 if o.units <= 6 else 2 if o.units <= 10 else 3 if o.units <= 15 else 4
            want = (int(o.date.strftime("%Y%m%d")), o.rider, o.user, o.units, band)
            if got.get(o.number) != want:
                mismatches.append((o.number, got.get(o.number), want))
        self.assertEqual(mismatches[:5], [], "%d orders differ from source" % len(mismatches))
        self.assertEqual(len(got), len(s.orders()))

    def test_line_values_are_quantity_times_rounded_list_price(self):
        self.assertZero("""SELECT count(*) FROM "FACT_ORDERITEM" f JOIN "DIM_PRODUCT" p USING ("productKey")
                           WHERE f."lineValue" <> round(f.quantity * p."listPrice", 2)""", "lineValue")
        self.assertZero('SELECT count(*) FROM "FACT_ORDERITEM" WHERE quantity <= 0', "non-positive quantity")

    def test_delivery_rows_agree_with_their_lines(self):
        self.assertZero("""SELECT count(*) FROM "FACT_ORDERDELIVERY" d
                           JOIN (SELECT "orderNumber", sum(quantity) q, count(*) n, min("deliveryDateKey") dk,
                                        min("riderKey") rk, max("riderKey") rk2, min("customerKey") ck,
                                        min("orderSizeKey") sk, max("orderSizeKey") sk2
                                 FROM "FACT_ORDERITEM" GROUP BY 1) i USING ("orderNumber")
                           WHERE d."totalQuantity" <> i.q OR d."lineItemCount" <> i.n OR d."orderCount" <> 1
                              OR d."deliveryDateKey" <> i.dk OR d."riderKey" <> i.rk OR i.rk <> i.rk2
                              OR d."customerKey" <> i.ck OR d."orderSizeKey" <> i.sk OR i.sk <> i.sk2""",
                        "delivery vs lines")
        self.assertZero("""SELECT count(*) FROM "FACT_ORDERDELIVERY" d JOIN "DIM_ORDERSIZE" z USING ("orderSizeKey")
                           WHERE d."totalQuantity" NOT BETWEEN z."minQuantity" AND z."maxQuantity" """, "size band")

    def test_rider_daily_is_a_complete_rider_by_day_grid(self):
        self.assertEqual(s.dw_scalar('SELECT count(*) FROM "FACT_RIDERDAILY"'), str(365 * 100))
        self.assertZero("""SELECT count(*) FROM "FACT_RIDERDAILY" r
                           LEFT JOIN (SELECT "deliveryDateKey" dk, "riderKey" rk, count(*) n, sum("totalQuantity") q,
                                             max("totalQuantity") mx
                                      FROM "FACT_ORDERDELIVERY" GROUP BY 1, 2) d
                                  ON d.dk = r."dateKey" AND d.rk = r."riderKey"
                           WHERE r."ordersDelivered" <> coalesce(d.n, 0) OR r."itemsDelivered" <> coalesce(d.q, 0)
                              OR r."maxBasket" <> coalesce(d.mx, 0)
                              OR r."isActiveDay" <> (coalesce(d.n, 0) > 0)::int""", "rider-day rollup")


class TestSummaryViews(IntegrityCase):
    """The AGG_* materialized views must be exact rollups of the base facts."""

    def test_category_and_product_views(self):
        base = """SELECT p.category, d.year, d.quarter, d."monthNumber", r."vehicleType", z."sizeGroup",
                         sum(f.quantity) u, sum(f."lineValue") v
                  FROM "FACT_ORDERITEM" f JOIN "DIM_PRODUCT" p USING ("productKey")
                  JOIN "DIM_DATE" d ON d."dateKey" = f."deliveryDateKey" JOIN "DIM_RIDER" r USING ("riderKey")
                  JOIN "DIM_ORDERSIZE" z USING ("orderSizeKey") GROUP BY 1, 2, 3, 4, 5, 6"""
        self.assertZero("""SELECT count(*) FROM (%s) b FULL JOIN "AGG_CATEGORY_PERIOD" a
                           ON (a.category, a.year, a.quarter, a."monthNumber", a."vehicleType", a."sizeGroup")
                            = (b.category, b.year, b.quarter, b."monthNumber", b."vehicleType", b."sizeGroup")
                           WHERE a.units IS DISTINCT FROM b.u OR a.value IS DISTINCT FROM b.v""" % base,
                        "AGG_CATEGORY_PERIOD")
        self.assertZero("""SELECT count(*) FROM (SELECT category, year, quarter, "monthNumber", "vehicleType",
                                  "sizeGroup", sum(units) u, sum(value) v FROM "AGG_PRODUCT_PERIOD"
                                  GROUP BY 1, 2, 3, 4, 5, 6) p
                           FULL JOIN "AGG_CATEGORY_PERIOD" a
                           ON (a.category, a.year, a.quarter, a."monthNumber", a."vehicleType", a."sizeGroup")
                            = (p.category, p.year, p.quarter, p."monthNumber", p."vehicleType", p."sizeGroup")
                           WHERE a.units IS DISTINCT FROM p.u OR a.value IS DISTINCT FROM p.v""",
                        "AGG_PRODUCT_PERIOD")

    def test_rider_day_view(self):
        self.assertZero("""SELECT count(*) FROM (SELECT "deliveryDateKey", "riderKey", "orderSizeKey",
                                  count(*) o, sum("totalQuantity") u FROM "FACT_ORDERDELIVERY" GROUP BY 1, 2, 3) b
                           FULL JOIN "AGG_RIDER_DAY" a USING ("deliveryDateKey", "riderKey", "orderSizeKey")
                           WHERE a.orders IS DISTINCT FROM b.o OR a.units IS DISTINCT FROM b.u""", "AGG_RIDER_DAY")

    def test_customer_view(self):
        self.assertZero("""SELECT count(*) FROM (SELECT f."customerKey", f."geoKey", d.year, d.quarter,
                                  count(DISTINCT f."orderNumber") o, sum(f.quantity) u, sum(f."lineValue") v
                                  FROM "FACT_ORDERITEM" f JOIN "DIM_DATE" d ON d."dateKey" = f."deliveryDateKey"
                                  GROUP BY 1, 2, 3, 4) b
                           FULL JOIN "AGG_CUSTOMER_PERIOD" a USING ("customerKey", "geoKey", year, quarter)
                           WHERE a.orders IS DISTINCT FROM b.o OR a.units IS DISTINCT FROM b.u
                              OR a.value IS DISTINCT FROM b.v""", "AGG_CUSTOMER_PERIOD")

    def test_views_are_populated(self):
        for view in ("AGG_CATEGORY_PERIOD", "AGG_PRODUCT_PERIOD", "AGG_RIDER_DAY", "AGG_CUSTOMER_PERIOD"):
            with self.subTest(view=view):
                self.assertEqual(s.dw_scalar("""SELECT relispopulated::text FROM pg_class
                                                WHERE relname = '%s' AND relkind = 'm'""" % view), "true")


class TestReadOnlyGuard(IntegrityCase):
    def test_the_suite_cannot_write(self):
        for run in (s.dw, s.src):
            with self.assertRaises(RuntimeError) as ctx:
                run("CREATE TEMP TABLE dwtest_probe (x int)")
            self.assertIn("read-only transaction", str(ctx.exception))

    def test_calendar_range(self):
        self.assertEqual(s.dw('SELECT min("fullDate"), max("fullDate") FROM "DIM_DATE"')[0],
                         [s.CAL_START.isoformat(), s.CAL_END.isoformat()])
        self.assertEqual(s.CAL_END, datetime.date(2025, 9, 23))


if __name__ == "__main__":
    unittest.main()
