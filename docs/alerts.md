# Alert và runbook

Bốn alert này đều xuất phát từ triệu chứng quan sát được trên dashboard, không từ
tên một implementation nội bộ. Nguồn số liệu là `data/logs.jsonl`; dashboard dùng
cửa sổ lùi 60 phút và tự refresh mỗi 30 giây. `observability-oncall` là vai trò
trực ca của nhóm Dashboard, SLO & Alert; trước khi nộp, ghi thành viên giữ vai trò
này trong `submission/REPORT.md`.

Khi xử lý bất kỳ alert nào, lưu lại thời điểm, giá trị metric, trace ID, session ID
và correlation ID đã dùng. Không chép message hoặc PII thô vào evidence.

## Alert 1

- Tên: `chat_latency_p95_slo_breach`.
- Severity: `warning`.
- SLI/SLO liên quan: `latency_p95_ms` — P95 của `response_sent.latency_ms` phải
  nhỏ hơn hoặc bằng 2 000 ms; mục tiêu là 99.5% cửa sổ 60 phút đạt ngưỡng.
- Điều kiện và thời gian duy trì: P95 > 2 000 ms trong cửa sổ 60 phút, kéo dài
  10 phút liên tiếp; chỉ đánh giá khi có ít nhất 20 response.
- Ảnh hưởng tới người dùng: nhóm request chậm nhất bắt đầu mất trên 2 giây để nhận
  câu trả lời, dễ gây chờ đợi hoặc retry.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel **Latency percentiles**, ghi P50/P95/P99, số response và
     khoảng thời gian 60 phút; xác nhận P95 vượt 2 000 ms thay vì chỉ một request lẻ.
  2. **Traces:** mở trace trong đúng thời điểm/cùng `session_id`, so sánh duration của
     các span con `retrieve-context`, `resolve-prompt` và `llm-generate` để khoanh span
     bất thường. Mỗi span dẫn tới một nguyên nhân khác nhau: `retrieve-context` chậm là
     lớp RAG, `resolve-prompt` chậm là Langfuse không phản hồi (kiểm tra `prompt_source`
     trên trace), `llm-generate` chậm là phía nhà cung cấp model.
  3. **Logs:** tìm `response_sent` theo `session_id` và mốc thời gian, lấy
     `correlation_id`, rồi đối chiếu chuỗi `request_received` → `response_sent` (hoặc
     `request_failed`) cùng ID đó trong `data/logs.jsonl`.
- Mitigation tạm thời: dừng hoặc rollback thay đổi mới làm chậm đường xử lý; nếu đây
  là practice incident đã được xác nhận, chỉ tắt bằng injector được lab cung cấp,
  sau đó tạo traffic mới và chờ P95 quay về ngưỡng trước khi đóng alert.
- Owner: `observability-oncall`.

## Alert 2

- Tên: `chat_error_rate_slo_breach`.
- Severity: `critical`.
- SLI/SLO liên quan: `error_rate_pct` —
  `count(request_failed) / count(request_received) * 100` phải nhỏ hơn hoặc bằng
  2%; mục tiêu là 99% cửa sổ 60 phút đạt ngưỡng.
- Điều kiện và thời gian duy trì: error rate > 2% trong cửa sổ 60 phút, kéo dài
  5 phút liên tiếp; chỉ đánh giá khi có ít nhất 20 request nhận vào.
- Ảnh hưởng tới người dùng: request trả lỗi hoặc không nhận được câu trả lời; đây là
  triệu chứng trực tiếp nên cần ưu tiên cao hơn latency/quality.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel **Error rate and breakdown**, ghi tỷ lệ, tử số/mẫu số và
     `error_type` đang tăng; kiểm tra traffic để loại trừ nhiễu khi mẫu quá nhỏ.
  2. **Traces:** lọc trace theo cùng thời điểm và `session_id`; xác định trace kết thúc
     lỗi hoặc span ném exception, không suy đoán nguyên nhân chỉ từ tên alert.
  3. **Logs:** tra `request_failed` bằng `session_id`/thời điểm để lấy
     `correlation_id`, rồi đọc tất cả event cùng ID và `error_type` đã được redact.
- Mitigation tạm thời: rollback cấu hình hoặc release mới liên quan nếu trace/log xác
  nhận; cô lập tính năng tùy chọn gây lỗi và trả lỗi an toàn. Không retry mù các thao
  tác có thể tạo side effect.
- Owner: `observability-oncall`.

## Alert 3

- Tên: `chat_quality_proxy_slo_breach`.
- Severity: `warning`.
- SLI/SLO liên quan: `quality_score_avg` — mean của `response_sent.quality_score`
  phải lớn hơn hoặc bằng 0.75; mục tiêu là 95% cửa sổ 60 phút đạt ngưỡng. Đây là
  quality proxy, cần xác minh thêm bằng sample response đã được redact.
- Điều kiện và thời gian duy trì: quality proxy trung bình < 0.75 trong cửa sổ 60
  phút, kéo dài 15 phút liên tiếp; chỉ đánh giá khi có ít nhất 20 response.
- Ảnh hưởng tới người dùng: câu trả lời có thể thiếu ngữ cảnh, ít liên quan hoặc giảm
  chất lượng dù API vẫn trả HTTP thành công.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel **Quality proxy**, ghi mean, số response và thời gian;
     kiểm tra đồng thời latency/error để biết đây có phải suy giảm chất lượng đơn lẻ.
  2. **Traces:** mở trace đại diện theo cùng thời điểm và `session_id`, kiểm tra
     metadata `prompt_name`, `prompt_label`, `prompt_version`, trạng thái prompt fetch
     và các span trước generation.
  3. **Logs:** dùng `session_id` và thời điểm trace để tìm `response_sent`, lấy
     `correlation_id`, rồi xác minh `quality_score`/metadata request trong log đã
     redaction; không ghi message thô vào ticket hay evidence.
- Mitigation tạm thời: nếu trace cho thấy prompt/version mới là nguồn suy giảm, chuyển
  label production về phiên bản đã biết tốt và ghi lại thao tác rollback thật; nếu chưa
  có bằng chứng, giữ alert mở và lấy sample đã redact trước khi thay đổi prompt.
- Owner: `observability-oncall`.

## Alert 4

- Tên: `chat_cost_budget_breach`.
- Severity: `warning`.
- SLI/SLO liên quan: `cost_total_usd` — tổng `response_sent.cost_usd` phải nhỏ hơn
  hoặc bằng 2.5 USD mỗi cửa sổ 60 phút.
- Điều kiện và thời gian duy trì: tổng cost > 2.5 USD trong cửa sổ 60 phút, kéo dài
  15 phút liên tiếp; chỉ đánh giá khi có ít nhất 20 response.
- Ảnh hưởng tới người dùng: không trực tiếp — người dùng vẫn nhận được câu trả lời.
  Đây là rủi ro tài chính, nên để `warning`: đánh thức người trực lúc 3h sáng vì hoá
  đơn là sai ưu tiên.
- Ba bước kiểm tra đầu tiên:
  1. **Metrics:** mở panel **Cost over time**, so `avg_cost_usd` và `tokens_out_total`
     với baseline. Chi phí tăng mà traffic không tăng nghĩa là **mỗi request** đắt lên,
     không phải do đông người dùng — hai nguyên nhân này cần hai cách xử lý khác nhau.
  2. **Traces:** sắp trace theo cost giảm dần, mở observation `llm-generate` và đọc
     `usage_details`. `completion_tokens` phình to là dấu hiệu model trả lời dài bất
     thường. Kiểm tra luôn `prompt_version` của các trace đắt tiền: nếu chúng dồn vào
     một version vừa được promote thì thủ phạm là thay đổi prompt.
  3. **Logs:** lấy `correlation_id` từ trace đắt nhất, đối chiếu `tokens_out` và
     `cost_usd` trong `data/logs.jsonl`; nhóm theo `feature` để biết phạm vi ảnh hưởng.
- Mitigation tạm thời: nếu nguyên nhân là prompt mới, rollback label `production` về
  version trước bằng `python scripts/prompt_versions.py rollback --version <n>` — có
  hiệu lực ngay, không cần deploy lại. Nếu không phải do prompt, đặt trần `max_tokens`.
- Owner: `observability-oncall`.
