# pii-masking-service

Service phát hiện và che PII cho dữ liệu báo cáo và log của các hệ thống (Cặp A – Đoàn Tuấn Long).
Kế hoạch và phạm vi: [docs/gate-0/gate-0.md](docs/gate-0/gate-0.md).

Sản phẩm gồm hai đầu ra dùng chung một lõi `piimask`:

1. **Tool** cho người duyệt: quét MongoDB, PostgreSQL, MySQL và file log, tài liệu (Excel, CSV, JSON,
   Parquet, `.log`, `.gz`), duyệt cách xử lý, xuất file đã che, sinh danh mục trường PII dạng JSON.
2. **API che PII**: các hệ thống gọi trước khi lưu log để nhận lại bản đã che.

## Hiện trạng

Repo mới chỉ chứa lõi mang sang từ dự án cũ (`tlong1610/PII_Masking`), đã bỏ UI, web API cũ, agent
LangGraph, vault, audit, RAG và các phụ thuộc LLM.

| Thư mục | Nội dung |
| --- | --- |
| `piimask/detection/` | Phát hiện PII: regex, từ điển, GLiNER (tùy chọn), quét theo tên trường và nội dung |
| `piimask/transform/` | Áp dụng hành động che: MASK, PARTIAL, HMAC, REDACT, DROP, NULLIFY, KEEP |
| `piimask/connectors/` | Đọc profile từ MongoDB và PostgreSQL (MySQL sẽ bổ sung) |
| `piimask/schemas.py`, `piimask/config.py` | Kiểu dữ liệu dùng chung, cấu hình qua biến môi trường |
| `tests/` | Test của các phần trên |
| `docs/gate-0/` | Tài liệu Gate 0 |

Sẽ bổ sung: bộ đọc file, API che, tool, sinh danh mục trường PII, script sinh mockup, Docker.

## Chạy test

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Test cần MongoDB đang chạy sẽ tự bỏ qua nếu không có.

## Quy định dữ liệu

Repo chỉ chứa dữ liệu mockup sinh bằng script. Không commit dữ liệu thật hay dữ liệu masked; không đưa
dữ liệu thật vào LLM.
