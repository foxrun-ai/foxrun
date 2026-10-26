# Cedar Shop test schema

## Collections
| Collection | Object type | Supertype | Lens | Database type | Who writes it |
|---|---|---|---|---|---|
| `products` | product | database | records | mirror | Shopify catalog feeder |
| `orders` | order | database | records | mirror | Shopify sales or ShipBob feeder |
| `order_lines` | order-line | database | records | mirror | Shopify sales or ShipBob feeder |
| `shipments` | shipment | database | records | mirror | ShipBob feeder |
| `stock_levels` | stock | database | records | mirror | ShipBob or Shopify catalog feeder |
| `customer_reviews` | customer-review | database | records | mirror | Review provider feeder; binding open |
| `stock_history` | stock_history | database | history | trend | Future local observation schedule |
| `restocks` | restock | database | records | table | Authorized local work |
| `receivings` | receiving | database | records | table | Authorized local work |
| `support_cases` | support-case | database | records | table | Authorized local work |
