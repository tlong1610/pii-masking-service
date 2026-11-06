# Hợp đồng API che PII

Hợp đồng máy đọc: [openapi-v1.json](openapi-v1.json), sinh từ code bằng `python -m api.openapi`. Test
`tests/test_api/test_contract.py` đỏ nếu file này lệch với code. Service chạy thì xem ở `/docs` và `/openapi.json`.

```bash
curl -s localhost:8000/v1/mask/text -H 'content-type: application/json' -d '{
  "schemaVersion": 1, "requestId": "demo-1", "context": "ticket", "locale": "vi",
  "text": "Gọi 0912345678, công tơ DEMO-001", "keep": ["METER_ID"]
}'
```

| HTTP | `status` | Bên gọi phải làm |
| --- | --- | --- |
| 200 | `OK` | Dùng `maskedText` |
| 422 | `INVALID_REQUEST` | Chặn lưu và gửi, sửa yêu cầu theo `errors` |
| 500 | `ERROR` | Chặn lưu và gửi |

Status khác `OK` không có `maskedText`, và phản hồi không lặp lại nội dung yêu cầu. Bên gọi cũng phải chặn khi không
nhận được phản hồi. `start`, `end` tính trên văn bản gốc. Họ tên có `type` là `NAME`.

## Phiên bản

| Phiên bản | Thay đổi |
| --- | --- |
| 1.0.0 | Bản đầu theo mục 8 của Gate 0. Bổ sung so với Gate 0: `keep` không bắt buộc; status `ERROR`, `INVALID_REQUEST` kèm `errors` (chỉ có tên trường và loại lỗi); `requestId` dài tối đa 128 ký tự và là `null` khi yêu cầu không đọc được; `GET /health` trả `status`, `maskerVersion`, `nerEnabled` |
