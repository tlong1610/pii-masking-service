# Quy trình phát triển MVP

Tài liệu này mô tả cách làm MVP từ nay đến CP3 (09/12/2026): làm gì ở từng bước, đánh giá bằng gì, và
test thế nào để chắc chắn sản phẩm kết nối được với hệ thống khác. Phạm vi, chỉ số và rủi ro lấy theo
[Gate 0](gate-0/gate-0.md).

Nguyên tắc chung: **dựng bộ đo trước, viết tính năng sau**. Mỗi tính năng chỉ coi là xong khi có test
và số đo không tụt so với baseline.

## 1. Mốc của chương trình

| Mốc | Ngày | Dữ liệu được dùng | Phải mang tới |
| --- | --- | --- | --- |
| Gate 1 | 11/11 | Mockup | Skeleton chạy end-to-end, kết quả kiểm chứng giả định rủi ro nhất, kế hoạch đã điều chỉnh, baseline metric, backlog Sprint 1 |
| CP1 | 18/11 | Mockup | Demo MVP, tiến độ so với kế hoạch |
| CP2 | 25/11 | Masked | Demo MVP, kết quả Sprint 1, retro |
| CP3 | 09/12 | Masked | Final demo, metric đo được, tài liệu bàn giao |

Sprint 1 chạy từ 12/11 đến 25/11, Sprint 2 từ 26/11 đến 09/12. Dữ liệu masked do mentor cấp trong tuần
19/11 – 25/11. Trước đó chỉ dùng mockup tự dựng.

## 2. Sản phẩm cần có ở CP3

| Đầu ra | Ai dùng | Mô tả |
| --- | --- | --- |
| Tool | Người duyệt (mentor, chuyên viên bảo vệ dữ liệu) | Kết nối MongoDB, PostgreSQL, MySQL hoặc nhận file tải từ S3 về; quét, duyệt cách xử lý, xuất file đã che; sinh danh mục trường PII |
| API che PII | Các hệ thống (.NET, hệ thống của Trung) | Nhận văn bản, bản ghi log hoặc file, trả lại bản đã che giữ nguyên cấu trúc |
| Danh mục trường PII | Đội phát triển .NET | File JSON ghi trường nào là PII, loại gì, hành động đề xuất; không chứa giá trị thật |
| Docker image | Mentor | Chạy tool và API bằng một lệnh |
| Tài liệu bàn giao | Người tiếp quản | Cách cài, chạy, mở rộng loại PII hoặc định dạng mới, đặc tả API |

## 3. Cấu trúc repo dự kiến

```text
piimask/            Lõi: phát hiện, chính sách, che (không phụ thuộc DB, file, LLM)
  detection/        Regex, từ điển, GLiNER, quét theo tên trường và nội dung
  transform/        MASK, PARTIAL, HMAC, REDACT, DROP, KEEP
  connectors/       Bộ đọc DB: MongoDB, PostgreSQL, MySQL
  readers/          Bộ đọc và ghi file: CSV, Excel, JSON, Parquet, .log, .gz
  catalog/          Sinh danh mục trường PII và JSON Schema của danh mục
api/                API che PII (HTTP, có OpenAPI)
tool/               Giao diện cho người duyệt
mockup/             Script sinh dữ liệu giả, nhãn chuẩn, danh mục chuẩn
eval/               Script đo recall, precision, độ chính xác danh mục, hiệu năng
tests/              unit, contract, integration, e2e, canary
docs/               Gate 0, quy trình này, tài liệu bàn giao
docker-compose.yml  Dựng DB mockup và service để chạy thử và test tích hợp
```

## 4. Các bước thực hiện

### Bước 1. Mockup và nhãn chuẩn (05/11 – 07/11)

Làm gì:

- Viết script sinh dữ liệu giả bằng Faker (locale `vi_VN`) với seed cố định.
- MongoDB trước: hai collection theo cấu trúc mẫu mentor gửi, cộng các collection bổ sung ở mục 9 của
  Gate 0 (khách hàng, thanh toán, nhân viên, ticket, thiết bị, log mô phỏng, collection lớn).
- Bộ file giả như file tải từ S3 về: CSV, Excel, JSON, Parquet, `.log` và bản nén `.gz`.
- PostgreSQL và MySQL làm ở Sprint 1, cùng cách sinh.
- Sinh kèm **file nhãn chuẩn**: mỗi trường (theo đường dẫn đầy đủ) có loại PII và hành động kỳ vọng; mỗi
  ô văn bản tự do có danh sách `{type, start, end}`; với file thì thêm tên file, sheet hoặc cột, số dòng.
- Sinh kèm **danh mục trường PII chuẩn** cho từng collection hoặc bảng.

Đánh giá:

- Chạy lại script với cùng seed ra đúng dữ liệu cũ.
- Mỗi loại PII có đủ mẫu để đo riêng (đề xuất ít nhất vài chục mẫu mỗi loại).
- Có đủ ca khó: tên trường mơ hồ, PII trong văn bản tự do, mã nghiệp vụ trông giống PII (mã vận đơn 12
  số, mã số thuế doanh nghiệp), trường lồng nhau, mảng, chuỗi JSON lồng, null, chuỗi rỗng.

Đầu ra: `mockup/` chứa script, file nhãn chuẩn và danh mục chuẩn. Dữ liệu sinh ra không commit.

### Bước 2. Bộ đo tự động (06/11 – 09/11)

Làm gì:

- Viết `eval/` so kết quả phát hiện với nhãn chuẩn, in bảng số theo từng loại PII và tổng.
- Đo cả danh mục trường PII: so file tool sinh ra với danh mục chuẩn.
- Đo thời gian quét và che, số bản ghi mỗi giây.
- Một lệnh chạy toàn bộ, ví dụ `make eval`, kết quả ghi ra file để so giữa các lần.

Đánh giá: chạy trên lõi hiện có ra được baseline đầu tiên.

Đầu ra: lệnh eval và file kết quả baseline.

### Bước 3. Skeleton end-to-end cho Gate 1 (07/11 – 11/11)

Làm gì:

- Nối lõi sẵn có thành luồng: đọc MongoDB → phát hiện → chọn hành động → che → xuất CSV hoặc XLSX.
- API che văn bản bản đầu (`POST /v1/mask/text`) và endpoint `/health`.
- Che được ít nhất một định dạng file (CSV) và file `.log`/`.gz`.
- Đóng gói Docker; `docker compose up` dựng MongoDB mockup và service.
- Kiểm chứng giả định rủi ro nhất: dữ liệu lồng nhau và việc giữ đúng định dạng file sau khi che.
- Chạy eval lấy baseline; điều chỉnh kế hoạch; lập backlog Sprint 1.

Đánh giá: luồng chạy trọn trên mockup; có số baseline; có kết luận cho từng giả định rủi ro (đúng, sai,
cần đổi hướng).

Đầu ra: demo Gate 1, baseline, kế hoạch điều chỉnh, backlog Sprint 1.

### Bước 4. Sprint 1 (12/11 – 25/11)

Làm gì, theo thứ tự ưu tiên:

1. Bộ đọc PostgreSQL và MySQL, cùng mockup cho hai loại này.
2. Bộ đọc và ghi lại các định dạng file còn lại (Excel, JSON, Parquet).
3. Sinh danh mục trường PII dạng JSON và JSON Schema của nó.
4. API che bản ghi log (`POST /v1/mask/record`) và che file (`POST /v1/mask/file`), có OpenAPI.
5. Tool giao diện cho người duyệt: kết nối, chọn phạm vi, xem kết quả, chọn hành động, xuất.
6. Test canary chạy trong mỗi lần build.

Đánh giá: mỗi tính năng có test; eval không tụt so với baseline; CP1 demo trên mockup; từ 19/11 chạy thử
trên dữ liệu masked.

Đầu ra: demo CP1 (18/11), demo CP2 (25/11) và retro Sprint 1.

### Bước 5. Sprint 2 (26/11 – 09/12)

Làm gì:

- Cải thiện các loại PII có recall hoặc precision thấp nhất theo bảng eval.
- Tích hợp với hệ thống của Trung theo pair contract (một chiều rồi hai chiều).
- Tối ưu tốc độ cho collection và file lớn (đọc theo lô, đọc từng dòng).
- Hoàn thiện tài liệu bàn giao; mentor tự cài và chạy thử.

Đánh giá: đạt các ngưỡng ở mục 5 của Gate 0 trên mockup có nhãn; chạy ổn định trên dữ liệu masked; mentor
chạy được không cần hỗ trợ.

Đầu ra: demo CP3, bảng số liệu cuối, tài liệu bàn giao.

## 5. Đánh giá: đo gì và đo thế nào

| Chỉ số | Cách tính | Dữ liệu | Ngưỡng |
| --- | --- | --- | --- |
| Recall PII mức nhạy cảm cao | Số PII phát hiện đúng ÷ tổng số PII trong nhãn chuẩn, tính theo từng loại | Mockup có nhãn | ≥ 95% |
| Precision theo trường | Số trường đánh dấu đúng là PII ÷ tổng số trường được đánh dấu | Mockup có nhãn | ≥ 90% |
| Độ chính xác danh mục trường PII | Recall và precision ở mức trường, so với danh mục chuẩn | Mockup có nhãn | Recall ≥ 95%, precision ≥ 90% |
| PII thô lọt ra ngoài | Số giá trị canary xuất hiện trong log ứng dụng, thông báo lỗi, phản hồi API, prompt LLM | Mockup | 0 |
| PII còn lại sau khi che | Quét lại file đã che, đếm PII mức nhạy cảm cao còn sót | Mockup | 0 |
| Thời gian quét và che | Thời gian cho collection mockup lớn nhất; số bản ghi mỗi giây với file | Mockup, sau đó masked | ≤ 10 phút mỗi dataset |
| Độ trễ API | Thời gian phản hồi p95 khi gọi với dòng log mockup | Mockup | Chờ mentor chốt |

Ngưỡng là đề xuất trong Gate 0, chờ mentor duyệt.

Lưu ý về dữ liệu masked: dữ liệu này đã bỏ PII và không có nhãn, nên **không dùng để tính recall**. Dùng
nó để kiểm tra luồng chạy, tốc độ, hình dạng dữ liệu thật và số lần tool báo nhầm trên dữ liệu đã che.

Báo cáo eval luôn ghi rõ số liệu lấy từ mockup hay masked.

## 6. Kiểm thử

### Các tầng test

| Tầng | Kiểm tra gì | Chạy khi nào |
| --- | --- | --- |
| Unit | Từng hàm phát hiện, từng hành động che, từng bộ đọc | Mỗi lần commit |
| Giữ nguyên dữ liệu | Đọc rồi ghi lại từng định dạng: mở được, đúng tên cột, kiểu, số dòng; JSON hợp lệ, giữ bộ khóa; HMAC vẫn nối được giữa các bảng | Mỗi lần commit |
| Canary | Gài giá trị PII đánh dấu vào mockup, chạy toàn bộ luồng, quét log, lỗi và phản hồi API; phải không thấy giá trị nào | Mỗi lần build |
| Contract | Phản hồi API đúng đặc tả OpenAPI; file danh mục khớp JSON Schema; định dạng trao đổi với Trung khớp pair contract | Mỗi lần build |
| Tích hợp | Kết nối DB thật chạy trong Docker (MongoDB, PostgreSQL, MySQL có mockup), quét, che, xuất | Mỗi lần build |
| End-to-end | Dựng toàn bộ bằng Docker, chạy luồng tool và gọi API, chạy eval | Trước mỗi mốc và trong CI |
| Hiệu năng | Thời gian xử lý collection và file lớn, độ trễ API | Gate 1 lấy baseline, sau đó trước mỗi checkpoint |

### Test để chắc chắn kết nối được

| Kết nối | Cách test | Đạt khi |
| --- | --- | --- |
| Tool với MongoDB, PostgreSQL, MySQL | `docker compose` dựng ba DB chứa mockup; test tích hợp kết nối bằng URI với tài khoản chỉ đọc, đọc, quét, xuất. Có lệnh hoặc nút kiểm tra kết nối | Kết nối được cả ba; báo lỗi rõ khi sai mật khẩu, sai host, thiếu quyền đọc; không bao giờ ghi vào DB nguồn |
| Tool với file tải từ S3 | Bộ file mẫu đủ mọi định dạng; đọc, che, ghi lại, so cấu trúc trước và sau | File đã che mở được bằng đúng định dạng gốc để mentor up lại |
| API với các hệ thống .NET | Đặc tả OpenAPI sinh từ code; contract test; ví dụ `curl` và bộ Postman để đội .NET gọi thử; endpoint `/health` | Gọi thử thành công từ ngoài container; phản hồi đúng định dạng đã công bố |
| Danh mục trường PII với .NET | JSON Schema cho file danh mục; test mọi file sinh ra đều khớp schema | File mới sinh luôn đọc được bằng schema đã công bố |
| API với hệ thống của Trung | Test theo định dạng ở mục 8 của Gate 0; hai bên chạy thử với mockup của nhau | Một chiều chạy được trong Sprint 1, hai chiều trong Sprint 2 |
| Toàn hệ thống | Test end-to-end trong Docker, gắn vào CI | Chạy xanh trên mỗi lần đẩy code |

## 7. Định nghĩa "xong" cho một đầu việc

- Có test cho phần mới, test cũ vẫn chạy xanh.
- Eval không tụt so với lần đo trước (hoặc ghi rõ lý do nếu đánh đổi có chủ đích).
- Test canary vẫn bằng 0.
- Không log hay in giá trị PII thô; lỗi khi che thì chặn lại, không trả về giá trị gốc.
- Chỉ dùng mockup hoặc dữ liệu masked; không commit dữ liệu; không đưa dữ liệu thật vào LLM.
- Cập nhật tài liệu nếu thay đổi cách dùng, API hoặc định dạng danh mục.

## 8. Danh sách kiểm tra trước từng mốc

**Gate 1 (11/11)**

- [ ] Mockup MongoDB và bộ file có nhãn chuẩn, sinh lại được
- [ ] Lệnh eval chạy được, có file baseline
- [ ] Luồng MongoDB → che → xuất CSV/XLSX chạy trọn
- [ ] API che văn bản và `/health` chạy trong Docker
- [ ] Kết luận cho giả định rủi ro nhất (dữ liệu lồng nhau, giữ định dạng file)
- [ ] Kế hoạch điều chỉnh và backlog Sprint 1

**CP1 (18/11)**

- [ ] Kết nối được cả ba loại DB với mockup
- [ ] Che và ghi lại đúng các định dạng file chính
- [ ] Sinh được danh mục trường PII khớp JSON Schema
- [ ] Test canary trong mỗi lần build
- [ ] Bảng eval so với baseline

**CP2 (25/11)**

- [ ] Chạy thử trên dữ liệu masked, ghi lại kết quả và lỗi gặp phải
- [ ] API che bản ghi và file có OpenAPI, contract test xanh
- [ ] Tool cho người duyệt đi trọn luồng
- [ ] Retro Sprint 1

**CP3 (09/12)**

- [ ] Đạt các ngưỡng ở mục 5 của Gate 0 trên mockup có nhãn
- [ ] Tích hợp với hệ thống của Trung có số liệu
- [ ] Mentor tự cài và chạy bằng Docker không cần hỗ trợ
- [ ] Tài liệu bàn giao: cài đặt, chạy, mở rộng, đặc tả API, định dạng danh mục
