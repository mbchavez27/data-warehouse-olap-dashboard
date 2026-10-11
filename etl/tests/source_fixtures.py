"""Small source datasets for the load tests, carrying the real data's dirty variants."""

from __future__ import annotations

TS = "2025-09-22 16:56:36"

DEFAULT_RIDERS = [
    (1, "Ana", "Cruz", "Bike", 1, 18, "Female"),
    (2, "Ben", "Reyes", "Motorbike", 2, 40, "M"),
    (3, "Cara", "Lim", "Trike", 1, 60, "F"),  # never delivers: idle every day
]

DEFAULT_PRODUCTS = [
    (1, "P1", "Tasty Wooden Fish", "TOYS", 1.77046),  # -> 1.77
    (2, "P2", "Practical Silk Keyboard", "make up", 3.27517),  # -> 3.28
    (3, "P3", "Incredible Metal Shirt", "Men's Apparel", 19.99),
]

# (order id, number, delivery date in either source format, rider, user)
DEFAULT_ORDERS = [
    (1, "ORD1", "2025-01-01", 1, 1),
    (2, "ORD2", "01/02/2025", 1, 2),
    (3, "ORD3", "2025-01-02", 2, 3),
    (4, "ORD4", "2025-01-03", 2, 1),
]

# (order id, product id, quantity); totals 6 / 10 / 11 / 16 hit all four bands
DEFAULT_ITEMS = [
    (1, 1, 6),
    (2, 1, 5),
    (2, 2, 5),
    (3, 3, 10),
    (3, 2, 1),
    (4, 1, 10),
    (4, 2, 6),
]


def seed_source(conn, *, riders=None, products=None, orders=None, items=None):
    conn.execute(
        'INSERT INTO "Couriers" ("id", "name", "createdAt", "updatedAt") VALUES '
        "(1, 'JNT', %s, %s), (2, 'LBCD', %s, %s)",
        (TS, TS, TS, TS),
    )
    cur = conn.cursor()
    cur.executemany(
        'INSERT INTO "Riders" ("id", "firstName", "lastName", "vehicleType", "courierId", '
        '"age", "gender", "createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [r + (TS, TS) for r in (riders or DEFAULT_RIDERS)],
    )
    users = [
        (1, "u1", "Dan", "Tan", "Manila", "Philippines", "1000", "Male"),
        (2, "u2", "Eve", "Go", "Manila", "Philippines", "1000", "female"),  # same triple as u1
        (3, "u3", "Fay", "Uy", "Manila", "Chile", "2000", "F"),  # same city, other country
    ]
    cur.executemany(
        'INSERT INTO "Users" ("id", "username", "firstName", "lastName", "city", "country", '
        '"zipCode", "gender", "createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [u + (TS, TS) for u in users],
    )
    cur.executemany(
        'INSERT INTO "Products" ("id", "productCode", "name", "category", "price", '
        '"createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s)',
        [p + (TS, TS) for p in (products or DEFAULT_PRODUCTS)],
    )
    cur.executemany(
        'INSERT INTO "Orders" ("id", "orderNumber", "deliveryDate", "deliveryRiderId", "userId", '
        '"createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s)',
        [o + (TS, TS) for o in (DEFAULT_ORDERS if orders is None else orders)],
    )
    cur.executemany(
        'INSERT INTO "OrderItems" ("OrderId", "ProductId", "quantity", "createdAt", "updatedAt") '
        "VALUES (%s, %s, %s, %s, %s)",
        [i + (TS, TS) for i in (DEFAULT_ITEMS if items is None else items)],
    )
    conn.commit()
