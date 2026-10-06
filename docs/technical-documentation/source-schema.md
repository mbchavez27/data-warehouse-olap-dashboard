# Source Database Schema (MySQL dump → `source_db`)

Visual reference for the raw dumps in `db/raw-dumps/`. Documentation only —
the executable schema lives in `db/source/init/01_source_schema.sql`.

```mermaid
erDiagram
    Couriers {
        int id PK
        varchar name
        datetime createdAt
        datetime updatedAt
    }
    Riders {
        int id PK
        varchar firstName
        varchar lastName
        varchar vehicleType
        int courierId FK "inferred → Couriers.id"
        int age
        varchar gender
        datetime createdAt
        datetime updatedAt
    }
    Users {
        int id PK
        varchar username
        varchar firstName
        varchar lastName
        varchar address1
        varchar address2
        varchar city
        varchar country
        varchar zipCode
        varchar phoneNumber
        varchar dateOfBirth "mixed formats: YYYY-MM-DD and MM/DD/YYYY"
        varchar gender
        datetime createdAt
        datetime updatedAt
    }
    Products {
        int id PK
        varchar productCode
        varchar category
        varchar description
        varchar name
        float price
        datetime createdAt
        datetime updatedAt
    }
    Orders {
        int id PK
        varchar orderNumber
        int userId FK "inferred → Users.id"
        varchar deliveryDate "mixed formats, see Users.dateOfBirth"
        int deliveryRiderId FK "inferred → Riders.id"
        datetime createdAt
        datetime updatedAt
    }
    OrderItems {
        int quantity
        varchar notes
        datetime createdAt
        datetime updatedAt
        int OrderId PK,FK "declared FK → Orders.id, CASCADE"
        int ProductId PK,FK "declared FK → Products.id, CASCADE"
    }

    Couriers ||--o{ Riders : "employs (inferred)"
    Users ||--o{ Orders : "places (inferred)"
    Riders ||--o{ Orders : "delivers (inferred)"
    Orders ||--|{ OrderItems : "contains (declared)"
    Products ||--|{ OrderItems : "listed-in (declared)"
```

## Relationship inventory

| # | From → To | Via | Declared in dump? |
|---|-----------|-----|-------------------|
| 1 | Couriers → Riders | `Riders.courierId` | No — inferred |
| 2 | Users → Orders | `Orders.userId` | No — inferred |
| 3 | Riders → Orders | `Orders.deliveryRiderId` | No — inferred |
| 4 | Orders → OrderItems | `OrderItems.OrderId`, ON DELETE/UPDATE CASCADE | Yes |
| 5 | Products → OrderItems | `OrderItems.ProductId`, ON DELETE/UPDATE CASCADE | Yes |

Inferred edges will be promoted to enforced `FOREIGN KEY`s in
`01_source_schema.sql` so orphan rows fail fast at load time.

## Raw volume (measured)

| Table | Rows | Size |
|-------|------|------|
| Couriers | 3 | 4 KB |
| Riders | 100 | 12 KB |
| Users | ~100,000 | 19 MB |
| Products | ~10,000 | 1.8 MB |
| Orders | ~1,000,000 | 84 MB |
| OrderItems | ~2,000,000 | 124 MB |
