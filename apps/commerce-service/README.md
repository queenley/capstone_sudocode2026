# commerce-service

Service sở hữu use case catalog/SKU, giá/quote, inventory và order boundary. FastAPI entry point: `src/main.py`.

Các package dưới `src/domain`, `src/application` và `src/infrastructure` mô tả ranh giới kiến trúc đích. Một phần handler/persistence hiện vẫn import từ `packages/backend-common`; process riêng không có nghĩa data/code ownership đã độc lập. Chuyển domain logic, repositories, migrations và tests vào service trước khi tách database.

Build từ root repo: `docker build -f apps/commerce-service/Dockerfile -t telesales-commerce:dev .`. Chạy local đầy đủ xem [root README](../../README.md).
