# Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: `high_api_latency`
- Severity: `high`
- SLI/SLO liên quan: P95 latency không vượt quá 3000 ms.
- Điều kiện và thời gian duy trì: `latency_p95_ms > 3000 for 5m`.
- Ảnh hưởng tới người dùng: Câu trả lời đến chậm, client có thể timeout hoặc gửi lại request.
- Ba bước kiểm tra đầu tiên:
  1. Xác định cửa sổ tăng P95 trên panel Latency.
  2. Mở trace chậm nhất và tìm span chiếm nhiều thời gian.
  3. Dùng correlation ID của trace để kiểm tra log, incident đang bật và lỗi dependency.
- Mitigation tạm thời: Tắt incident nếu có, giảm concurrency hoặc chuyển về prompt/model ổn định trong khi điều tra dependency chậm.
- Owner: `observability-oncall`.

## Alert 2

- Tên: `elevated_api_error_rate`
- Severity: `critical`
- SLI/SLO liên quan: Error rate không vượt quá 2%.
- Điều kiện và thời gian duy trì: `error_rate_pct > 2 for 5m`.
- Ảnh hưởng tới người dùng: Request thất bại hoặc không nhận được câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Xem breakdown `error_type` và thời điểm lỗi bắt đầu.
  2. Mở một trace lỗi đại diện để xác định generation/tool span thất bại.
  3. Tìm `request_failed` có cùng correlation ID và kiểm tra dependency liên quan.
- Mitigation tạm thời: Tắt feature/incident gây lỗi, retry có giới hạn hoặc chuyển sang fallback an toàn.
- Owner: `observability-oncall`.

## Alert 3

- Tên: `low_response_quality`
- Severity: `warning`
- SLI/SLO liên quan: Quality proxy trung bình không thấp hơn 0.75.
- Điều kiện và thời gian duy trì: `quality_score_avg < 0.75 for 15m`.
- Ảnh hưởng tới người dùng: Câu trả lời ngắn, thiếu context hoặc không đáp ứng yêu cầu.
- Ba bước kiểm tra đầu tiên:
  1. Khoanh vùng feature, prompt label và model có quality thấp.
  2. So sánh trace với baseline, kiểm tra prompt version và tài liệu RAG đã lấy.
  3. Kiểm tra log cùng correlation ID để loại trừ lỗi, redaction quá mức hoặc input bất thường.
- Mitigation tạm thời: Rollback label `production` về prompt baseline đã xác nhận và theo dõi quality sau rollback.
- Owner: `ai-quality-oncall`.
