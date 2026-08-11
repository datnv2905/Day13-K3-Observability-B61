# Dựng và kiểm tra dashboard

`config/dashboard.yaml` là contract chấm điểm dùng chung, không phụ thuộc việc nhóm dựng dashboard trong Langfuse hay một công cụ local. File này quy định đúng nguồn dữ liệu, phép tổng hợp, đơn vị và threshold cho sáu panel.

Trường `query` trong YAML là pseudocode mô tả phép tính, không phải câu lệnh để copy nguyên vào mọi công cụ. Nhóm chuyển cùng logic đó sang cú pháp của công cụ đã chọn.

## Mapping dữ liệu

| Panel | Event/field | Phép tổng hợp |
|---|---|---|
| Latency | `response_sent.latency_ms` | P50, P95, P99 |
| Traffic | `request_received` | count, request/phút |
| Errors | `request_received`, `request_failed`, `error_type` | error rate và breakdown |
| Cost | `response_sent.cost_usd` | tổng theo phút và toàn cửa sổ |
| Tokens | `response_sent.tokens_in/tokens_out` | tổng theo từng field |
| Quality | `response_sent.quality_score` | mean |

Giữ time range mặc định 60 phút, refresh 30 giây và hiển thị threshold/SLO line. Giá trị chính xác nằm trong `config/dashboard.yaml`; không tự đổi contract chỉ để ảnh dashboard đẹp hơn.

## Cách dựng

1. Hoàn thiện logging/PII và chạy API.
2. Chạy `python scripts/load_test.py --concurrency 5` để tạo baseline.
3. Dùng `data/logs.jsonl` làm nguồn chuẩn để tạo đúng sáu panel bằng Streamlit, notebook, Grafana hoặc công cụ tương đương. Langfuse vẫn là nơi mở trace/prompt version để điều tra sâu.
4. Đặt tên panel, đơn vị và threshold giống contract.
5. Chạy validator:

```bash
python scripts/validate_dashboard.py
```

Validator kiểm tra cấu trúc contract; nó không thể chứng minh biểu đồ trong ảnh dùng đúng dữ liệu. Evidence runtime vẫn bắt buộc.

## Dashboard runtime của nhóm

Repo triển khai dashboard không cần dependency bổ sung ngay trong FastAPI. Sau khi chạy API, mở:

```text
http://127.0.0.1:8000/dashboard
```

Dashboard đọc `data/logs.jsonl`, lọc cửa sổ 60 phút, tự refresh mỗi 30 giây và hiển thị đúng sáu panel cùng threshold từ `config/dashboard.yaml`. Dữ liệu tổng hợp dạng JSON có tại `/dashboard/data` để kiểm tra hoặc tích hợp công cụ khác.

## Cách kiểm tra runtime

1. Lưu ảnh baseline và giá trị P95/error/cost hiện tại.
2. Bật một incident practice, ví dụ `python scripts/inject_incident.py --scenario rag_slow`.
3. Chạy lại load test với cùng input và concurrency.
4. Xác nhận panel liên quan thay đổi theo đúng hướng; với `rag_slow`, P95 phải tăng rõ ràng.
5. Mở trace chậm và tìm log có cùng correlation ID.
6. Tắt incident bằng `python scripts/inject_incident.py --scenario rag_slow --disable`.

Ảnh dashboard phải nhìn được tên panel, time range, đơn vị và threshold. Báo cáo phải dẫn lại trace ID hoặc log line dùng để giải thích thay đổi.
