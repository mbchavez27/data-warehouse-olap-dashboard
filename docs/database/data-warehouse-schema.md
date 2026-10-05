# Data Warehousing Schema

- This displays the schema used for the data warehousing

```mermaid
erDiagram
    FACT_SALES {
        int sale_id PK
        int date_id FK
        int product_id FK
        float total_amount
    }
    DIM_PRODUCT {
        int product_id PK
        string product_name
    }

    DIM_PRODUCT ||--o{ FACT_SALES : "describes"
```
