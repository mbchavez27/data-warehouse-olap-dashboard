"""Canonical read-only queries for extracting source rows."""

DATE_SOURCE_SQL = 'SELECT DISTINCT "deliveryDate" FROM "Orders"'

RIDER_SOURCE_SQL = (
    'SELECT r."id", r."firstName", r."lastName", r."vehicleType", r."courierId", '
    'c."name", r."age", r."gender" '
    'FROM "Riders" r LEFT JOIN "Couriers" c ON c."id" = r."courierId" ORDER BY r."id"'
)

GEOGRAPHY_SOURCE_SQL = (
    'SELECT DISTINCT "country", "city", "zipCode" FROM "Users" ORDER BY 1, 2, 3'
)

CUSTOMER_SOURCE_SQL = (
    'SELECT "id", "username", "firstName", "lastName", "gender" '
    'FROM "Users" ORDER BY "id"'
)

PRODUCT_SOURCE_SQL = (
    'SELECT "id", "productCode", "name", "category", "price"::text '
    'FROM "Products" ORDER BY "id"'
)

DELIVERY_SOURCE_SQL = """
SELECT o."id", o."orderNumber", o."deliveryDate", o."deliveryRiderId", o."userId",
       coalesce(i.units, 0), coalesce(i.lines, 0)
FROM "Orders" o
LEFT JOIN (
  SELECT "OrderId", sum("quantity") AS units, count(*) AS lines
  FROM "OrderItems" GROUP BY "OrderId"
) i ON i."OrderId" = o."id"
ORDER BY o."id"
"""

ITEM_SOURCE_SQL = """
SELECT oi."OrderId", oi."ProductId", oi."quantity",
       o."orderNumber", o."deliveryDate", o."deliveryRiderId", o."userId",
       sum(oi."quantity") OVER (PARTITION BY oi."OrderId") AS units
FROM "OrderItems" oi JOIN "Orders" o ON o."id" = oi."OrderId"
ORDER BY oi."OrderId", oi."ProductId"
"""

CUSTOMER_ADDRESS_SOURCE_SQL = (
    'SELECT "id", "country", "city", "zipCode" FROM "Users"'
)
