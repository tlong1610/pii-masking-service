# Tóm tắt Gate 1 (11/11)

Skeleton đã chạy trọn trên mockup, nhưng độ chính xác còn xa mục tiêu.

> **API hiện chưa dùng được với dữ liệu thật.** API trả `status: OK` trong khi chưa che được họ tên, địa chỉ, ngày sinh,
> mật khẩu, token và GPS, và chưa có xác thực. Chỉ dùng với mockup cho tới khi xong mục 1, 2, 4, 8 và 9 của backlog.

## Skeleton chạy những gì

- `docker compose up` dựng MongoDB mockup (kèm user chỉ đọc), nạp mockup và chạy service.
- Một lệnh chạy trọn luồng MongoDB → phát hiện → chính sách → che → CSV và XLSX. Mảng tách thành file con có khóa cha đã
  HMAC. `report.json` ghi hành động từng trường, không chứa giá trị.
- API `GET /health`, `POST /v1/mask/text`, OpenAPI tự sinh. Lỗi khi che thì chặn lại, không trả văn bản gốc.
- Che file CSV, `.log`, `.gz`, giữ nguyên cấu trúc.
- Test: đơn vị, hợp đồng OpenAPI, canary, tích hợp với MongoDB và service trong Docker.

## Cách tự chạy thử

```bash
cp .env.example .env                  # điền HMAC_SECRET: openssl rand -hex 32
docker compose up -d --build
curl localhost:8000/health
curl -s localhost:8000/v1/mask/text -H 'content-type: application/json' -d '{"schemaVersion":1,"requestId":"demo",
  "context":"ticket","locale":"vi","text":"Gọi 0912345678, công tơ DEMO-001","keep":["METER_ID"]}'
mkdir -p data/export
docker compose run --rm --user "$(id -u):$(id -g)" export     # file đã che ở data/export
```

## Baseline

Đo trên mockup, chỉ regex và quy tắc, GLiNER tắt. Số đầy đủ ở `eval/results/baseline.json`. Ngưỡng chờ mentor duyệt.

| Độ chính xác | Recall (mục tiêu ≥ 95%) | Precision (mục tiêu ≥ 90%) | Recall nhóm nhạy cảm |
| --- | --- | --- | --- |
| Trường MongoDB | 60,5% | 83,9% | 100% (2 trường) |
| Văn bản tự do | 51,7% | 75,3% | 89,7% |
| Dòng log | 54,3% | 77,1% | 0% |
| Log object | 50,0% | 100% | 0% |

CSV, Excel, JSON, Parquet chưa đo vì chưa có bộ đọc trong eval.

**Rò rỉ trên 100.000 document:** dò toàn bộ file đã che, 254.277/1.185.729 giá trị PII gốc còn sót (21,4%), CSV và XLSX
bằng nhau. Tất cả là mã khách hàng và số khung của khách cá nhân; họ tên, CCCD, email, số điện thoại, địa chỉ, số tài
khoản, số thẻ và mã số thuế ở trường có cấu trúc còn 0. Phần này chưa tính văn bản tự do: trên mockup nhỏ, ghi chú ticket
còn sót 285/590 thực thể.

**Trường PII hiếm gài vào 100.000 document:** bộ quét chỉ xem 100 document đầu nên phát hiện 2/8 trường.

| Ca | Số trường | Bộ quét phát hiện | Giá trị gốc còn sót |
| --- | --- | --- | --- |
| Có ít nhất 1 document trong 100 đầu | 2 | 2 | 0 |
| Chỉ có sau document 50.000, trường mới | 5 | 0 (che toàn bộ vì chưa có kết luận) | 0 |
| Trường đã kết luận không phải PII, về sau có PII | 1 | 0 | **35/35** |

| Tốc độ (100.000 document, 200.096 dòng, 14 CPU) | Thời gian | Tốc độ |
| --- | --- | --- |
| Quét, che, xuất CSV | 19,2 giây | 5.206 document/giây |
| Quét, che, xuất CSV và XLSX | 87,7 giây | 1.140 document/giây |
| API, văn bản 156 ký tự, gọi tuần tự | p50 1,28 ms, p95 1,62 ms | |

Bộ nhớ đỉnh 115 MB khi quét và xuất. Chưa đo tốc độ khi bật GLiNER.

## Kết luận giả định rủi ro

**Dữ liệu lồng nhau: đúng về cấu trúc, chưa đạt về phát hiện.** Tách mảng, mảng trong mảng và nối bằng khóa HMAC đã có test.
Bộ quét chưa vào trong mảng, chưa qua 2 cấp lồng, chưa đọc chuỗi JSON lồng và chỉ lấy mẫu 100 document đầu. Che toàn bộ
trường chưa có kết luận giữ được an toàn nhưng làm mất dữ liệu: 117/198 cột trong mockup. Trường đã kết luận KEEP thì không
có lớp bảo vệ này, như ca 35/35 ở trên.

**Giữ định dạng file: đúng với CSV, `.log`, `.gz`; chưa kiểm chứng Excel, JSON, Parquet.** CSV giữ bảng mã, dấu phân cách, tên
cột, số dòng. `.log` giữ số dòng, `.gz` được nén lại. Có một lỗi đã tái hiện: PII dạng số trong dòng log JSON bị thay
bằng thẻ không có dấu nháy làm hỏng JSON.

## Kế hoạch điều chỉnh

So với Bước 4 trong `docs/quy-trinh-mvp.md`: làm các lỗ hổng che trước, PostgreSQL và MySQL xuống sau. Lý do là recall hiện 50–60%,
nhóm nhạy cảm trong log 0%, trong khi connector chỉ lặp lại cách làm của MongoDB. Thứ tự backlog là tạm thời, có thể đổi
theo kết quả đo.

## Backlog Sprint 1 (12/11–25/11)

1. Che mật khẩu, token, khóa API, session, IP, GPS trong log.
2. Quét trong mảng, trường lồng sâu, chuỗi JSON lồng; sửa cách lấy mẫu của bộ quét; sửa lỗi làm hỏng JSON khi che số trong
   dòng log JSON (thêm ca này vào mockup trước).
3. Danh mục trường PII dạng JSON kèm JSON Schema.
4. Bật GLiNER, đo riêng bật và tắt, đưa vào image.
5. Mã khách, số khung, serial theo chính sách ngữ cảnh, gồm điều kiện khách doanh nghiệp.
6. Che Excel, JSON, Parquet; thêm vào eval.
7. PostgreSQL, MySQL cùng mockup.
8. Regex ngày sinh, số điện thoại viết cách quãng; giảm báo nhầm.
9. Xác thực API, giới hạn độ dài, timeout; `/v1/mask/record`, `/v1/mask/file`.
10. Giao diện người duyệt; canary trong mỗi lần build.
