# sales-service

Service sở hữu use case customer CRM, conversations, messages, handoff và assignment. FastAPI entry point: `src/main.py`.

Các package dưới `src/domain`, `src/application` và `src/infrastructure` mô tả ranh giới kiến trúc đích. Một phần handler/persistence hiện vẫn import từ `packages/backend-common`; process riêng không có nghĩa data/code ownership đã độc lập. Chuyển domain logic, repositories, migrations và tests vào service trước khi tách database.

Build từ root repo: `docker build -f apps/sales-service/Dockerfile -t telesales-sales:dev .`. Chạy local đầy đủ xem [root README](../../README.md).
