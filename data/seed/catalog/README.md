# Catalog

This folder holds structured product, promotion, and policy artifacts.

Expected files:
- catalog_skus.csv
- synthetic_sku_variants.csv
- promotions.csv
- policies.csv
- product_images.json (optional): a photo per product of the BTC catalogue

## Product photos

`product_images.json` maps a product (`SKU-AP-X`) to a picture the storefront serves
(`apps/web/public/products/SKU-AP-X.jpg`) and its credit (title, author, licence, source).
The seed (`scripts.seed.catalog`) stores both in `commerce.products.image_url` / `image_credit`;
a product not in the file shows its category's drawing.

The pictures come from [Openverse](https://openverse.org), only under licences a shop may use
(CC0, public domain, CC BY, CC BY-SA). They illustrate the kind of product, not the model
(half the catalogue is made up), and the product page says so with the credit CC BY asks for.
Every pick was reviewed by eye; `"locked": true` marks a reviewed pick.

```powershell
py -3.12 scripts/seed/product_images.py --candidates SKU-FAN-SEN --out sheet.jpg   # numbered candidates (.json has their ids)
py -3.12 scripts/seed/product_images.py --use SKU-FAN-SEN=<openverse id>           # take one, locked
py -3.12 scripts/seed/product_images.py --sheet sheet.jpg                           # every picked photo, to review
docker compose build seed web; docker compose run --rm seed; docker compose up -d web
```

Without a reviewed picture (no fitting one on Openverse on 2026-10-25): SKU-AF-6L, SKU-FAN-SEN,
SKU-FAN-TWR, SKU-JK-DWN, SKU-JK-WND, SKU-MB-BAG, SKU-MB-MON, SKU-MB-STER, SKU-SN-SOCK,
SKU-WF-RO9, SKU-WF-RO10, SKU-WF-UF, SKU-XM-4P.
