# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: B61 (cập nhật tên hiển thị nếu lớp có quy ước khác)
- Repository URL: https://github.com/datnv2905/Day13-K3-Observability-B61
- Commit SHA cuối: Cập nhật sau commit nộp bài cuối cùng
- Thành viên và vai trò: Nguyễn Trọng Toàn — Logging & PII; Tracing & Prompt Versioning; Dashboard, SLO & Alerts; Report & Evidence

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: 100/100
- Tổng số traces: 28 (xác nhận qua Langfuse API sau practice run)
- Số PII leak còn lại: 0
- Link/đường dẫn dashboard: http://127.0.0.1:8000/dashboard

## 3. Logging và tracing

- Evidence correlation ID: `submission/evidence/cp1-logging-pii.md`
- Evidence PII redaction: `submission/evidence/cp1-logging-pii.md`
- Evidence trace waterfall: `submission/evidence/cp2-trace-waterfall.png`
- Giải thích một span đáng chú ý: generation `run` của trace baseline mất khoảng 1.06 giây, liên kết prompt `day13-chat` v1 và ghi nhận model, token, cost; trace ID và metadata cho phép nối ngược về log bằng session/correlation context.

## 4. Prompt versioning

- Prompt name: `day13-chat`
- Version/label baseline: version 1, labels cuối `baseline`, `production`
- Version/label candidate: version 2, labels cuối `candidate`, `latest`
- Trace ID của mỗi version: baseline `41dcfe875f88da75f4190bd0ec712cb0`; candidate `ca55680b65fa8370e375fdb81d6f72fa`
- Bằng chứng đổi label hoặc rollback: production v2 `6885f08e8b2afcedad56e68531411e3b`; production rollback v1 `3012069c364eb7e195d188d33389b0a2`; chi tiết tại `submission/evidence/cp2-langfuse-traces.md`

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: `HỢP LỆ: 6/6 panel có trong dashboard contract.`
- Evidence dashboard: `submission/evidence/cp2-dashboard.png` và `submission/evidence/cp2-dashboard-validator.txt`; runtime tại `/dashboard`.
- SLO đã chọn và lý do: P95 ≤ 3000 ms, error ≤ 2%, daily cost ≤ 2.5 USD, quality ≥ 0.75; đây là các ngưỡng trực tiếp phản ánh tốc độ, độ tin cậy, ngân sách và chất lượng người dùng.
- Alert rules và runbook: `config/alert_rules.yaml` và `docs/alerts.md`; gồm high latency, elevated error rate và low quality.

## 6. Điều tra challenge

- Challenge ID: Chờ Lab Coach xác nhận release challenge chính thức
- Triệu chứng từ metrics: Chưa chạy challenge chính thức
- Trace ID liên quan: Chưa có
- Log line/correlation ID liên quan: Chưa có
- Root cause: Chưa kết luận khi chưa có evidence chính thức
- Fix action: Chưa áp dụng
- Preventive measure: Sẽ cập nhật sau điều tra theo luồng Metrics → Traces → Logs

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Trọng Toàn | Hoàn thiện structured logging, correlation ID và PII redaction; cấu hình Langfuse tracing; tạo prompt v1/v2, chuyển label và rollback production; xây dashboard 6 panel; thiết kế SLO, alert, runbook; tổng hợp report và evidence | Cập nhật SHA sau commit cuối | Hiểu cách nối Metrics → Traces → Logs bằng correlation ID; quản lý prompt bằng version/label; kiểm soát PII trước khi ghi log; thiết kế dashboard và alert dựa trên SLO; kết luận sự cố bằng evidence có thể kiểm chứng |
